"""
build_calendar_multi.py — 全分析師統一「calendar-time 多持有期」表 + FDR

用已驗證可重現原始 $221 的 calendar-time 引擎（call 頻率加權、只算持倉日超額、
週分批 t），對每位分析師掃 5/20/60/120/250 天（slice window），或依 Call 自帶
的明確時間窗（explicit/scale）計算。

三層框架：
  第1層（策略表現）：praw 累積 — 看多持有、看空持現金（收尾①，不放空）
  第2層（分類標籤）：由 analysts.py 的 label 欄位標記
  第3層（預測準度）：pex（sign×(標的−大盤)）命中率；
                     is_market_bet=True 時另算大盤絕對方向命中率

收尾①：praw 看空→現金（max(sign,0)×標的報酬）；pex 仍用 sign 衡量看空準度
收尾②：per-call 時間窗（Call dict 帶 T_start/T_end；pending 自動跳過）
收尾③：is_market_bet=True 時輸出 direction_hit_rate（大盤絕對方向命中率）
收尾④：analysts.py 統一註冊表，加新人只需填 dict + loader
收尾⑤：stats() 補 max_drawdown / hit_rate / beat_mkt

回歸保證：強制 slice 模式（全部 Call 沒有 T_end）時輸出與舊版逐欄一致。

輸出：calendar_multi.json
"""
from __future__ import annotations
import json, os, pickle, sqlite3
from collections import defaultdict
from math import erf, sqrt
import numpy as np
import pandas as pd
import config
import analysts as ana
from rw_core import weekly_excess, romano_wolf_reject

HOLDS = [5, 20, 60, 120, 250]
COST  = 0.006
ANN   = 52
KOL_START    = pd.Timestamp("2024-04-01")
GOOAYE_START = pd.Timestamp("2020-03-01")
TODAY        = pd.Timestamp.now().normalize()
OUT          = "calendar_multi.json"

# ── 逐筆判尺：全站唯一的分類，掛在「每筆 call 的 target」上，不掛在人身上 ──────
#   個股/產業ETF  → benchmark = 該市場大盤指數（問「選股贏大盤沒」＝selection）
#   大盤/資產本身  → benchmark = 自身買進持有（問「擇時方向對沒」＝timing）
# 要維護的只有兩張小表（資產字典，跟分析師無關；新增資產類別才動）：
INDEX_OF = {"tw": "TAIEX", "us": "SPY"}   # 各市場的股票指數
def _asset_proxy_set():
    try:
        from extract_predictions import ASSET_TICKER
        base = set(ASSET_TICKER.values())
    except Exception:
        base = set()
    # 大盤指數本身 + 廣泛資產類別（債/商品）ETF：這些比自身，不比股票指數
    return base | {"SPY", "TAIEX", "GLD", "BTC-USD", "TLT", "DBC", "EWH", "FXI", "EWT"}
ASSET_PROXY = _asset_proxy_set()

def market_of(target, tagged=None):
    """回傳 target 的市場 {tw,us}。優先用 call 自帶的 market；否則由代碼推（4 碼數字＝台股）。"""
    if tagged in ("tw", "us"):
        return tagged
    if tagged == "commodity":
        return "us"      # 商品代理（GLD/BTC…）走 ASSET_PROXY→自身，市場僅供指數查詢用
    t = str(target)
    return "tw" if (t.isdigit() and len(t) == 4) else "us"

def benchmark_for(target, market=None):
    """全站唯一判尺：資產/大盤代理→自身；個股→該市場指數。回傳 benchmark 的 ticker。"""
    if target in ASSET_PROXY:
        return target
    return INDEX_OF.get(market_of(target, market), target)

def is_timing_call(target, market=None):
    """這筆是不是『擇時型』（benchmark 就是自身）＝target 是大盤/資產代理。"""
    return benchmark_for(target, market) == target


def pval_t(t, dfree):
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))


def _parse_call(c):
    """統一拆 Call（dict 或舊式 tuple）→ (sid, ts, sign, wtype, t_end_str, t_start_str)。"""
    if isinstance(c, dict):
        return (c["target"], pd.Timestamp(c["date"]), c.get("sign", 1),
                c.get("window_type", "slice"), c.get("T_end"), c.get("T_start"))
    sid, ts = c[0], c[1]
    sign = c[2] if len(c) > 2 else 1
    return (sid, pd.Timestamp(ts), sign, "slice", None, None)


def resolve_span(c, cal, cal_pos, default_hold):
    """把一筆 call 解析成日曆上的 (entry_pos, hold_days)，或 None。全站唯一窗定義，所有人／所有窗型同一套：
      1. 進場 = 開口日 ts 之後第一個交易日；無未來交易日 → None（不能在他開口前行動）。
      2. 意圖結束 intended_end：
           explicit 窗（window_type!='slice' 且有 T_end）→ T_end。
           slice 窗 → 進場日 + default_hold 個交易日。
      3. 實際結束 = min(intended_end, 資料末日 cal[-1])；撞資料邊界就裁切，**一筆都不丟**
         （calendar-time 逐日 mark-to-market；未結算窗也計入「已走完的那幾天」）。
      4. hold_days = 進場到實際結束的交易日數（≥1）；不足 1 → None。
    回傳 (entry_pos, hold_days)。target 存不存在由呼叫端自行檢查。
    """
    _sid, ts, _sign, wtype, t_end_str, t_start_str = _parse_call(c)
    fut = cal[cal > ts]
    if len(fut) == 0:
        return None
    ei = cal_pos[fut[0]]                       # 進場＝開口日後第一個交易日
    if wtype != "slice" and t_end_str:
        intended_end = pd.Timestamp(t_end_str)
    else:
        end_i = min(ei + default_hold, len(cal) - 1)
        intended_end = cal[end_i]
    # 一律 mark-to-market 到資料末日（截止日還沒走完＝看他到截止日的報酬，不 pending、不整筆丟）
    actual_end = min(intended_end, cal[-1])
    end_pos = int((cal <= actual_end).sum()) - 1
    hold_days = end_pos - ei
    if hold_days < 1:
        return None
    return ei, hold_days


def _bkey(c, sid):
    """這筆 call 的 benchmark ticker（逐筆判尺；見 benchmark_for）。"""
    mkt = c.get("market") if isinstance(c, dict) else None
    return benchmark_for(sid, mkt)


def build_curve(calls, ret, cal, cal_pos, hold, cost=COST):
    """
    統一引擎。calls: List[Call dict] 或舊式 tuple。ret: 全站價格池 {ticker: 日報酬(對齊 cal)}。

    逐筆判尺（人不分類）：每筆持倉的 benchmark = benchmark_for(target,market)——
      個股→該市場指數、大盤/資產→自身。策略腿減「各自的 benchmark」＝逐筆配對超額。
    基準腿 braw：把每筆 call 的 benchmark 買進持有（sign 一律 +1、cost=0）同期間彙總
      ＝全站「$100 買對應大盤」線（配對買進持有，取代舊 buyhold_bench_ret）。
    窗定義一律走 resolve_span（開口日進場、裁切不丟、mark-to-market）。

    回傳：praw, praw_both, praw_short, pex_long, pex_short, act_long, act_short, braw。
    """
    holding  = defaultdict(list)     # d → [(sid, sign, bkey)]
    newentry = defaultdict(int)      # 看多進場（計成本）
    newentry_s = defaultdict(int)    # 看空進場
    seen = set()

    for c in calls:
        sid, ts, sign, *_ = _parse_call(c)
        key = (sid, ts, sign)
        if key in seen:
            continue
        seen.add(key)
        if sid not in ret:
            continue
        bkey = _bkey(c, sid)
        if bkey not in ret:          # benchmark（指數）沒價 → 無法配對，略過
            continue
        span = resolve_span(c, cal, cal_pos, hold)
        if span is None:
            continue
        ei, call_hold = span
        for d in range(ei, min(ei + call_hold, len(cal))):
            holding[d].append((sid, sign, bkey))
        if sign > 0:
            newentry[ei] += 1
        else:
            newentry_s[ei] += 1

    praw = []; praw_both = []; praw_short = []
    pex_long = []; pex_short = []
    act_long = []; act_short = []
    braw = []                         # 配對基準腿（買對應指數/自身）
    idx  = []

    def _r(t, d):
        return ret[t].get(cal[d], np.nan)

    for d in range(1, len(cal)):
        held   = holding.get(d, [])
        longs  = [(s, sg, bk) for s, sg, bk in held if sg > 0]
        shorts = [(s, sg, bk) for s, sg, bk in held if sg < 0]
        ne_l = newentry.get(d, 0); ne_s = newentry_s.get(d, 0)
        # ── 配對基準腿：所有持倉的 benchmark 買進持有（+1，不擇時）──
        bvs = [_r(bk, d) for _, _, bk in held]
        bvs = [x for x in bvs if pd.notna(x)]
        braw.append(float(np.mean(bvs)) if bvs else 0.0)
        # ── 看多模式 praw ──
        if not longs:
            praw.append(0.0); act_long.append(False); pex_long.append(0.0)
        else:
            raws = [_r(s, d) for s, _, _ in longs]
            raws = [x for x in raws if pd.notna(x)]
            cost_l = (ne_l / len(longs)) * cost
            praw.append((np.mean(raws) if raws else 0.0) - cost_l)
            exl = [(_r(s, d) - _r(bk, d)) for s, _, bk in longs]
            exl = [x for x in exl if pd.notna(x)]
            pex_long.append((np.mean(exl) - cost_l) if exl else 0.0)
            act_long.append(True)
        # ── 看空腿準度（不放空，僅記準度）：sign×(標的−自身benchmark) ──
        if not shorts:
            pex_short.append(0.0); act_short.append(False)
        else:
            exs = [sg * (_r(s, d) - _r(bk, d)) for s, sg, bk in shorts]
            exs = [x for x in exs if pd.notna(x)]
            pex_short.append(np.mean(exs) if exs else 0.0)
            act_short.append(True)
        # ── 純看空模式 praw_short：放空他看壞的 ──
        if not shorts:
            praw_short.append(0.0)
        else:
            sret = [-_r(s, d) for s, _, _ in shorts]
            sret = [x for x in sret if pd.notna(x)]
            scost = (ne_s / len(shorts)) * cost
            praw_short.append((np.mean(sret) if sret else 0.0) - scost)
        # ── 雙向模式 praw_both ──
        allpos = []
        for s, _, _ in longs:
            v = _r(s, d)
            if pd.notna(v): allpos.append(v)
        for s, _, _ in shorts:
            v = _r(s, d)
            if pd.notna(v): allpos.append(-v)
        if allpos:
            bcost = ((ne_l + ne_s) / (len(longs) + len(shorts))) * cost
            praw_both.append(float(np.mean(allpos)) - bcost)
        else:
            praw_both.append(0.0)
        idx.append(cal[d])

    return (pd.Series(praw,       index=idx),
            pd.Series(praw_both,  index=idx),
            pd.Series(praw_short, index=idx),
            pd.Series(pex_long,   index=idx),
            pd.Series(pex_short,  index=idx),
            pd.Series(act_long,   index=idx),
            pd.Series(act_short,  index=idx),
            pd.Series(braw,       index=idx))


def brinson_allocation(calls, stock_ret, cal, cal_pos, hold):
    """配置效果（Brinson-Hood-Beebower 1986）：他相對『自己平均曝險』的動態偏重，
    有沒有押對市場。中性 = 各資產的時間平均權重（固定）→ 只評動態偏離、原諒
    結構性偏好（見 §5.5）。只計看多持倉（配置＝往哪個市場加碼）。
      配置日報酬 = Σ_i (w_i,d − w̄_i) × r_i,d   （w=當日該資產佔持倉比、w̄=時間平均）
    回傳日報酬序列（供週分批 t）；持倉日 < 10 回 None。統一機構：任何多資產型自動套用。"""
    holding = defaultdict(list)             # day → [看多資產 sid]
    seen = set()
    for c in calls:
        sid, ts, sign, *_ = _parse_call(c)
        if sign <= 0:                       # 只看多腿（配置＝加碼哪個市場）
            continue
        key = (sid, ts)
        if key in seen or sid not in stock_ret:
            continue
        seen.add(key)
        # ── 全站唯一窗定義（見 resolve_span）──
        span = resolve_span(c, cal, cal_pos, hold)
        if span is None:
            continue
        ei, call_hold = span
        for d in range(ei, min(ei + call_hold, len(cal))):
            holding[d].append(sid)

    days, wvecs = [], []
    for d in range(1, len(cal)):
        held = holding.get(d, [])
        if not held:
            continue
        tot = len(held)
        w = defaultdict(float)
        for s in held:
            w[s] += 1.0 / tot
        days.append(d); wvecs.append(w)
    if len(days) < 10:
        return None
    assets = set().union(*[set(w) for w in wvecs])
    neutral = {a: float(np.mean([w.get(a, 0.0) for w in wvecs])) for a in assets}  # 平均曝險
    alloc, idx = [], []
    for d, w in zip(days, wvecs):
        r = 0.0
        for a in assets:
            ra = stock_ret[a].get(cal[d], np.nan)
            if pd.notna(ra):
                r += (w.get(a, 0.0) - neutral[a]) * ra
        alloc.append(r); idx.append(cal[d])
    return pd.Series(alloc, index=idx)


def _leg(series, act):
    """回傳一條腿的 {excess_ann,t,p,ci,n_weeks,hit}；不足回 None。"""
    s = series[act]
    if len(s) == 0:
        return None
    wk = s.groupby(s.index.to_period("W")).mean()
    n = len(wk)
    if n < 3:
        return None
    m = float(wk.mean()); se = float(wk.std(ddof=1) / sqrt(n))
    t = m / se if se > 0 else 0.0
    return {
        "excess_ann": round(((1 + m) ** ANN - 1) * 100, 1),
        "ci_lo": round(((1 + (m - 1.96 * se)) ** ANN - 1) * 100, 1),
        "ci_hi": round(((1 + (m + 1.96 * se)) ** ANN - 1) * 100, 1),
        "t": round(t, 2), "p": round(pval_t(t, n - 1), 4), "n_weeks": n,
        "hit": round(float((s > 0).mean()) * 100, 1),
    }


def stats(praw, praw_both, praw_short, pex_long, pex_short, act_long, act_short, braw):
    """
    做多/看空分開列 + 三模式 $ 曲線（看多/雙向/看空）：
      headline = 做多腿（散戶實際；FDR 也用這條）
      modes = {long, both, short} 的 $ 終值與曲線（both/short 為假設放空）
      KOL 全做多 → 看空腿 None、both==long、short 空 → 前端不顯示切換鈕。
    """
    L = _leg(pex_long, act_long)
    S = _leg(pex_short, act_short)   # 可能 None（無看空，如 KOL）
    if L is None and S is None:
        return None                  # 兩腿都沒資料才放棄

    cum  = (1 + praw).cumprod()
    mcum = (1 + braw.reindex(praw.index).fillna(0)).cumprod()
    step = max(1, len(cum) // 36)
    roll_max = cum.cummax()
    max_dd = round(float(((cum - roll_max) / roll_max).min()) * 100, 1) if len(cum) else 0.0
    pr_act = praw[act_long]
    hit_rate = round(float((pr_act > 0).mean()) * 100, 1) if len(pr_act) > 0 else None

    # CAPM 報酬拆解（算術年化，可加：跟單 = 市場β貢獻 + 選股α）
    capm = None
    if len(pr_act) > 30:
        bl = braw.reindex(pr_act.index).fillna(0)
        bvar = float(bl.var())
        if bvar > 0:
            beta = float(((pr_act - pr_act.mean()) * (bl - bl.mean())).mean() / bvar)
            a_d = float(pr_act.mean() - beta * bl.mean())
            follow_a = float(pr_act.mean()) * 252 * 100
            mkt_a = beta * float(bl.mean()) * 252 * 100
            alpha_a = a_d * 252 * 100
            capm = {"beta": round(beta, 2), "follow": round(follow_a, 1),
                    "market": round(mkt_a, 1), "alpha": round(alpha_a, 1)}
            # Treynor-Mazuy(1966) 擇時項：r_p = α + β·r_m + γ·r_m²（學派 A 補完）
            # γ>0 顯著 = 大盤漲時 beta 更高（動態擇時本事）；γ≈0 = 靜態 beta，非擇時。
            b = bl.values; y = pr_act.values
            X = np.column_stack([np.ones_like(b), b, b * b])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            n_obs, k = len(y), X.shape[1]
            if n_obs > k:
                resid = y - X @ coef
                s2 = float(resid @ resid) / (n_obs - k)
                se_g = float(s2 * np.linalg.inv(X.T @ X)[2, 2]) ** 0.5
                capm["timing_gamma"] = round(float(coef[2]), 3)
                capm["timing_t"] = round(float(coef[2]) / se_g, 2) if se_g > 0 else 0.0

    # 三模式 $ 曲線
    has_short = bool(act_short.any())
    cum_both  = (1 + praw_both).cumprod()
    cum_short = (1 + praw_short).cumprod()
    def _ds(c): return [round(float(v), 4) for v in c.values[::step]] if len(c) else []
    modes = {
        "long":  {"follow_end": round(float(cum.iloc[-1] * 100), 1) if len(cum) else None,
                  "curve": _ds(cum)},
    }
    if has_short:
        modes["both"]  = {"follow_end": round(float(cum_both.iloc[-1] * 100), 1),
                          "curve": _ds(cum_both)}
        modes["short"] = {"follow_end": round(float(cum_short.iloc[-1] * 100), 1),
                          "curve": _ds(cum_short)}

    out = {
        "has_short": has_short,
        "modes": modes,
        # headline = 做多腿（無做多則 None，如全看空的 DAC）
        "excess_ann": L["excess_ann"] if L else None,
        "ci_lo": L["ci_lo"] if L else None, "ci_hi": L["ci_hi"] if L else None,
        "t": L["t"] if L else None, "p": L["p"] if L else None,
        "n_weeks": L["n_weeks"] if L else None,
        "follow_end": round(float(cum.iloc[-1] * 100), 1) if len(cum) else None,
        "mkt_end":    round(float(mcum.iloc[-1] * 100), 1) if len(mcum) else None,
        "curve":  [round(float(v), 4) for v in cum.values[::step]] if len(cum) else [],
        "mcurve": [round(float(v), 4) for v in mcum.values[::step]] if len(mcum) else [],
        "dates":  [str(d.date()) for d in praw.index[::step]] if len(praw) else [],
        "max_drawdown": max_dd,
        "hit_rate": hit_rate,
        "capm": capm,                           # 報酬拆解（市場β vs 選股α）
        "beat_mkt": L["hit"] if L else None,    # 做多贏大盤率
        # ── 看空腿（分開列；無看空則 None）──
        "short_excess_ann": S["excess_ann"] if S else None,
        "short_t":          S["t"] if S else None,
        "short_hit":        S["hit"] if S else None,
        "short_n_weeks":    S["n_weeks"] if S else None,
    }
    return out


def per_call_scorecard(calls, close_dict, cal, horizons, rep_hold=20):
    """一次 per-call 計分（取代 direction_hit_rate + tally_hits）。逐筆依 target 判尺：
       timing 型（benchmark=自身，大盤/資產）→ 記『方向命中』；
       selection 型（benchmark=市場指數，個股/產業）→ 逐 horizon 記『贏大盤』(excess>0)。
    回傳 {"dir": {direction_hit_rate,...,bull/bear}, "hc": {h:{long/short:{hit,miss,pend}}}}。"""
    c_all = w_all = pend = 0
    c_bull = w_bull = c_bear = w_bear = 0
    hc = {str(h): {"long": {"hit": 0, "miss": 0, "pend": 0},
                   "short": {"hit": 0, "miss": 0, "pend": 0}} for h in horizons}
    for c in calls:
        tgt = c.get("target"); mkt = c.get("market")
        close = close_dict.get(tgt)
        if close is None:
            continue
        ts = pd.Timestamp(c["date"]); sign = c.get("sign", 1)
        if is_timing_call(tgt, mkt):
            # 方向命中：explicit 用自帶窗、slice 用代表窗 rep_hold；意圖窗未走完＝pending
            wtype = c.get("window_type", "slice")
            if wtype == "explicit" and c.get("T_end"):
                t0 = pd.Timestamp(c.get("T_start") or c["date"])
                intended_end = pd.Timestamp(c["T_end"])
            else:
                pos = cal.searchsorted(ts)
                if pos + 1 >= len(cal):
                    continue
                t0 = ts
                intended_end = cal[min(pos + rep_hold, len(cal) - 1)]
            if intended_end > TODAY:
                pend += 1; continue
            t1 = min(intended_end, close.index[-1])
            p0 = close.asof(t0); p1 = close.asof(t1)
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                continue
            ret = p1 / p0 - 1
            hit = 1 if ((sign == 1 and ret > 0) or (sign == -1 and ret < 0)) else 0
            if hit: c_all += 1
            else:   w_all += 1
            if sign == 1: c_bull += hit; w_bull += (1 - hit)
            else:         c_bear += hit; w_bear += (1 - hit)
        else:
            # 贏大盤：逐 horizon，target 對照它的市場指數
            bench_close = close_dict.get(benchmark_for(tgt, mkt))
            if bench_close is None:
                continue
            pos = cal.searchsorted(ts); leg = "long" if sign > 0 else "short"
            for h in horizons:
                if pos + 1 >= len(cal):
                    continue
                if pos + h >= len(cal):
                    hc[str(h)][leg]["pend"] += 1; continue
                t1 = cal[pos + h]
                a = _fwd_ret(close, ts, t1); b = _fwd_ret(bench_close, ts, t1)
                if a is None or b is None:
                    continue
                win = (a - b) > 0 if sign > 0 else (b - a) > 0
                hc[str(h)][leg]["hit" if win else "miss"] += 1

    def _rate(c, w):
        tot = int(c + w)
        return (round(c / tot * 100, 1) if tot else None), tot
    rate, total = _rate(c_all, w_all)
    br, bn = _rate(c_bull, w_bull); br2, bn2 = _rate(c_bear, w_bear)
    return {"dir": {"direction_hit_rate": rate, "n_direction_settled": total,
                    "n_direction_pending": pend,
                    "bull_dir_hit": br, "n_bull_settled": bn,
                    "bear_dir_hit": br2, "n_bear_settled": bn2},
            "hc": hc}


def _fwd_ret(close, t0, t1):
    """close 從 t0 到 t1 的報酬（asof 對齊）。不足回 None。"""
    p0 = close.asof(t0); p1 = close.asof(t1)
    if pd.isna(p0) or pd.isna(p1) or p0 == 0:
        return None
    return float(p1 / p0 - 1)


def _eval_window(close, bench_close, t0, t1, sign, is_market_bet,
                 matched_bench=False, is_pending=False, contributes=True):
    """單一窗結算 → dict(strat, bench, excess, hit) 或 None。與 resolve_span 對齊，三態：
      contributes=False（意圖窗尚未於真實時間走完）→ 不計入 $（strat=None）、hit=pending。
      contributes=True 且 is_pending=True（已走完但資料落後、窗被裁切）→ 給目前為止的
        mark-to-market $（對得上曲線），但準度未定 → hit=pending。
      contributes=True 且 is_pending=False（完整觀測）→ 正常判 hit/miss。
    [t0,t1] 為裁切到資料末日的實際持有窗；matched_bench=True → 基準用該筆標的自身買進持有。"""
    if not contributes:
        return dict(strat=None, bench=None, excess=None, hit="pending")
    a_ret = _fwd_ret(close, t0, t1)
    b_ret = a_ret if matched_bench else _fwd_ret(bench_close, t0, t1)
    if a_ret is None or b_ret is None:
        return None
    strat = a_ret if sign > 0 else 0.0          # 看空→現金
    excess = strat - b_ret
    if is_pending:
        hit = "pending"
    else:
        hit = ("hit" if (sign * a_ret) > 0 else "miss") if is_market_bet \
            else ("hit" if excess > 0 else "miss")
    return dict(strat=round(strat * 100, 1), bench=round(b_ret * 100, 1),
                excess=round(excess * 100, 1), hit=hit)


def build_call_results(calls, close_dict, cal,
                       mode="full", rep_hold=20, top_n=5, horizons=None):
    """
    統一八欄預測紀錄表。逐筆判尺（人不分類）：每筆 call 的 benchmark = benchmark_for(target,market)；
    timing 型（benchmark=自身）hit=方向、selection 型 hit=贏大盤。
    slice 窗 → 每筆 dict(...,byh={h:{...}})；explicit 窗 → 每筆單一窗扁平 dict。
    strat: 看多=標的報酬、看空=現金0%。hit: pending/命中/未中。
    mode: "full"=全列；"topbottom"=依代表天期超額取最神/最雷各 top_n。
    """
    rows = []
    for c in calls:
        tgt = c.get("target"); mkt = c.get("market")
        close = close_dict.get(tgt)
        if close is None:
            continue
        # 逐筆判尺
        bench_close = close_dict.get(benchmark_for(tgt, mkt))
        if bench_close is None:
            continue
        mb = is_timing_call(tgt, mkt)      # timing→hit看方向、基準=自身；selection→hit看贏大盤
        ts = pd.Timestamp(c["date"])
        sign = c.get("sign", 1)
        wtype = c.get("window_type", "slice")
        dlabel = "看多" if sign > 0 else "看空"
        multi = (horizons is not None)

        # 多天期（slice 窗）：每個天期各結算一次（開口日進場、撞資料末日裁切不丟）
        if multi and not (wtype == "explicit" and c.get("T_end")):
            pos = cal.searchsorted(ts)
            byh = {}
            for h in horizons:
                if pos + 1 >= len(cal):
                    continue                             # 開口後無交易日
                # slice 意圖窗＝ts+h 交易日；以日曆位置算（資料在手即視為已於真實時間走完，
                # 只是可能被資料末日裁切）→ contributes=True、is_pending=資料未達窗尾。
                trunc = pos + h >= len(cal)
                t1 = cal[min(pos + h, len(cal) - 1)]     # 裁切到資料末日
                ev = _eval_window(close, bench_close, ts, t1, sign,
                                  mb, mb, is_pending=trunc, contributes=True)
                if ev is None:
                    continue
                ev["period"] = f"{str(ts.date())}+{h}日"
                byh[str(h)] = ev
            if byh:
                rows.append(dict(date=c["date"], summary=c.get("summary", tgt),
                                 full=c.get("full", c.get("summary", tgt)),
                                 dir=dlabel, byh=byh))
            continue

        # 單一窗（explicit 或 is_market_bet）：開口日 ts 進場、t1 裁切到資料末日
        t0 = ts
        if wtype == "explicit" and c.get("T_end"):
            intended_end = pd.Timestamp(c["T_end"])
        else:
            pos = cal.searchsorted(t0)
            intended_end = cal[min(pos + rep_hold, len(cal) - 1)]
        # $ 一律顯示到截止日（mark-to-market，與曲線一致）；hit 僅在意圖窗尚未於真實時間走完時標 pending（與命中率視角一致）
        trunc = intended_end > TODAY
        t1 = min(intended_end, cal[-1])                  # 裁切不丟
        period = f"{str(t0.date())}~{str(t1.date())}"
        ev = _eval_window(close, bench_close, t0, t1, sign, mb,
                          mb, is_pending=trunc, contributes=True)
        if ev is None:
            continue
        ev["period"] = period
        rows.append(dict(date=c["date"], summary=c.get("summary", tgt),
                         full=c.get("full", c.get("summary", tgt)),
                         dir=dlabel, **ev))

    if mode == "topbottom":
        if horizons is not None:
            key = str(rep_hold)
            # rows 可能混合：slice 筆有 byh、explicit 筆是扁平（有自帶時間窗）
            def _rex(r):
                return r["byh"].get(key, {}).get("excess") if "byh" in r else r.get("excess")
            settled = [r for r in rows if _rex(r) is not None]
            settled.sort(key=lambda r: _rex(r), reverse=True)
        else:
            settled = [r for r in rows if r["hit"] != "pending" and r["excess"] is not None]
            settled.sort(key=lambda r: r["excess"], reverse=True)
        rows = settled[:top_n] + settled[-top_n:] if len(settled) > 2 * top_n else settled
    else:
        rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def coverage(calls, close_dict) -> dict:
    """價格覆蓋率稽核：哪些標的在快取裡查無價格 → 被引擎靜默跳過。
    回傳 {n_targets,n_missing,missing[:50],n_calls,n_calls_dropped}。
    不改任何計算，只把『默默漏掉』變成可見、可審。"""
    def _tgt(c):
        return c["target"] if isinstance(c, dict) else c[0]
    targets = {_tgt(c) for c in calls}
    missing = sorted(t for t in targets if t not in close_dict)
    mset = set(missing)
    dropped = sum(1 for c in calls if _tgt(c) in mset)
    return {"n_targets": len(targets), "n_missing": len(missing),
            "missing": missing[:50], "n_calls": len(calls),
            "n_calls_dropped": dropped}


def event_path(calls, close_dict, cal, pre=20, post=20):
    """喊買日前後 ±pre/post 交易日的標的平均正規化走勢（喊買日=100）。
    看出「喊買前已漲多少（追漲）、喊買後還漲不漲」。只取看多 call。
    回傳 {days,path,n} 或 None（有效 call < 5）。搬自 archive/build_event_study.py，
    改由統一引擎每次重算並存進 cm（原為凍結的 event_study.json）。"""
    rows = []
    for c in calls:
        tgt = c["target"] if isinstance(c, dict) else c[0]
        sign = (c.get("sign", 1) if isinstance(c, dict) else c[2])
        if sign <= 0:
            continue
        s = close_dict.get(tgt)
        if s is None:
            continue
        ts = pd.Timestamp(c["date"] if isinstance(c, dict) else c[1])
        pos = cal.searchsorted(ts)
        if pos < pre or pos + post >= len(cal):
            continue
        p0 = s.asof(cal[pos])
        if pd.isna(p0) or p0 == 0:
            continue
        seg, ok = [], True
        for off in range(-pre, post + 1):
            pv = s.asof(cal[pos + off])
            if pd.isna(pv):
                ok = False; break
            seg.append(pv / p0 * 100)
        if ok:
            rows.append(seg)
    if len(rows) < 5:
        return None
    arr = np.array(rows)
    return {"days": list(range(-pre, post + 1)),
            "path": [round(float(v), 2) for v in arr.mean(axis=0)],
            "n": len(rows)}


STATE = "data_cache/engine_state.pkl"   # 增量重算用：上次全跑的 per-analyst 中間結果

def run(only: str | None = None):
    """only=名字 → 只重算該分析師，其他人沿用上次快取（wk_series/rec 原樣保留），
    Romano-Wolf/家族統計照常對全體重算（bootstrap 固定 seed，未動的人數字不變）。
    需要先全跑過一次留下 STATE 快取。"""
    results = {}
    all_p   = []
    cov_warn = []   # 收集缺價警告，結尾統一印出
    wk_series = {}  # {(name,h): 週超額序列} → Romano-Wolf 判決用

    if only:
        if not os.path.exists(STATE):
            raise SystemExit(f"✗ --only 需要 {STATE}（先全跑一次：python build_calendar_multi.py）")
        st_prev = pickle.load(open(STATE, "rb"))
        results   = {k: v for k, v in st_prev["results"].items() if k != only}
        all_p     = [t for t in st_prev["all_p"] if t[0] != only]
        wk_series = {k: v for k, v in st_prev["wk_series"].items() if k[0] != only}
        print(f"▶ 增量模式：只重算「{only}」，其他 {len(results)} 位沿用快取")

    # ── 共用價格資料 ──────────────────────────────────────────
    data = pickle.load(open("full_price_cache.pkl", "rb"))
    taiex  = data["taiex"]
    taiex  = taiex[~taiex.index.duplicated()].sort_index()
    prices = data["prices"]

    pxc = json.loads(open("data_cache/gooaye_predict_px.json", encoding="utf-8").read())
    etf_close = {}
    for t, d in pxc.items():
        s = pd.Series(d); s.index = pd.to_datetime(s.index); etf_close[t] = s.sort_index()
    # ★ 末日凍結（使用者定調 BACKTEST_END 不解凍）：所有價格序列（含日曆源）
    # 一律裁到凍結日。否則各快取檔抓價日期不一（誰新抓過就延到誰的日期），
    # mark-to-market 窗會隨「今天跑了什麼更新」漂移、連帶改動別人的數字。
    _freeze = pd.Timestamp(config.BACKTEST_END)
    taiex     = taiex[taiex.index <= _freeze]
    etf_close = {t: s[s.index <= _freeze] for t, s in etf_close.items()}
    spy      = etf_close["SPY"]
    kol_close = {s: c[~c.index.duplicated()].sort_index() for s, c in prices.items()}
    kol_close = {s: c[c.index <= _freeze] for s, c in kol_close.items()}

    # 台股交易日曆（KOL 用）
    cal_tw     = taiex.index[taiex.index >= KOL_START]
    cal_tw_pos = {d: i for i, d in enumerate(cal_tw)}

    # 美股交易日曆（股癌/DAC 用）
    cal_us     = spy.index[spy.index >= GOOAYE_START]
    cal_us_pos = {d: i for i, d in enumerate(cal_us)}

    # ── 全域價格池（廢除 per-analyst universe）：所有市場合併成單一池 ──────
    # 任何 call 的 target／benchmark 都在同一池找價，跟「誰喊的」無關；
    # universe 只剩「挑哪條交易日曆」（主市場），不再限制能查哪些價。
    close_pool: dict = dict(kol_close)          # 台股個股（已去重排序）
    close_pool["TAIEX"] = taiex
    for t, s in etf_close.items():              # 美股 ETF/資產代理 + SPY
        close_pool.setdefault(t, s)
    import glob
    for p in sorted(glob.glob("data_cache/*_px.json")):  # 多資產預言型資產快取（wu + add_analyst 新增的 {slug}_px.json）
        for t, d in json.loads(open(p, encoding="utf-8").read()).items():
            if t not in close_pool:
                s = pd.Series(d); s.index = pd.to_datetime(s.index)
                close_pool[t] = s.sort_index()[lambda x: x.index <= _freeze]

    registry = {**ana.kol_registry(), **ana.ANALYSTS}
    # 主市場＝挑哪條日曆（台股→TW 曆、其餘→US 曆）；價格池全域共用
    def home_of(cfg):
        return "tw" if cfg.get("market") == "台股" else "us"

    # 先載入所有 call（loader 只跑一次），收集「實際被引用的 ticker」──
    # 只 reindex 這些（不是全池 ~2000 支），大幅縮短建置時間。
    prewarm: dict = {}
    needed: set = set()
    for name, cfg in registry.items():
        loader = ana.LOADERS.get(cfg["loader_key"])
        if loader is None:
            print(f"⚠ 略過 {name}：未知 loader_key='{cfg['loader_key']}'"); continue
        calls = loader(cfg) or []
        prewarm[name] = (cfg, calls)
        for c in calls:
            t = c["target"] if isinstance(c, dict) else c[0]
            if not t:
                continue
            needed.add(t)
            needed.add(benchmark_for(t, c.get("market") if isinstance(c, dict) else None))
    needed &= set(close_pool)                   # 只留有價的
    def _ret_on(cal):
        return {t: close_pool[t].reindex(cal, method="ffill").pct_change() for t in needed}
    ret_tw = _ret_on(cal_tw); ret_us = _ret_on(cal_us)
    CALS = {
        "tw": dict(ret=ret_tw, close=close_pool, cal=cal_tw, cal_pos=cal_tw_pos),
        "us": dict(ret=ret_us, close=close_pool, cal=cal_us, cal_pos=cal_us_pos),
    }

    if only and only not in prewarm:
        raise SystemExit(f"✗ 名冊裡沒有「{only}」，現有：{'、'.join(prewarm)}")
    for name, (cfg, calls) in prewarm.items():
        if only and name != only:
            continue
        U = CALS[home_of(cfg)]
        if not calls:
            print(f"⚠ 略過 {name}：loader 無資料"); continue
        rec = {"market": cfg["market"], "label": cfg["label"], "horizons": {}}
        # ── 淨值曲線 + 配對基準（逐筆判尺，人不分類）──
        for h in HOLDS:
            praw, pb, psh, pl, ps, al, ash, braw = build_curve(
                calls, U["ret"], U["cal"], U["cal_pos"], h)
            st = stats(praw, pb, psh, pl, ps, al, ash, braw)
            if st:
                rec["horizons"][str(h)] = st
                wk = weekly_excess(pl, al)
                if len(wk) >= 10:
                    wk_series[(name, str(h))] = wk
                if st["p"] is not None:
                    all_p.append((name, str(h), st["p"]))
        # ── 近 12 個月「共同窗」：同一段日曆(BACKTEST_END 前 365 天)對所有人，只算 20 日年化超額 ──
        # 供排行榜「近12個月」切換做 apples-to-apples 對比（避免不同人追蹤長度不一）。
        _w0 = pd.Timestamp(config.BACKTEST_END) - pd.Timedelta(days=365)
        _recent = [c for c in calls if pd.Timestamp(str(c["date"])) >= _w0]
        if len(_recent) >= 5:
            _s20 = stats(*build_curve(_recent, U["ret"], U["cal"], U["cal_pos"], 20))
            if _s20 and _s20.get("excess_ann") is not None:
                rec["n_calls_1y"] = len(_recent)
                # 近12個月三數同用「累積」，讓 實賺 − 大盤 = 超額 對得起來（非年化週超額）：
                #   實賺＝含大盤累積、大盤＝同期買進持有累積、超額＝兩者相減
                if _s20.get("follow_end") is not None and _s20.get("mkt_end") is not None:
                    rec["raw_ret_1y"] = round(_s20["follow_end"] - 100, 1)
                    rec["mkt_ret_1y"] = round(_s20["mkt_end"] - 100, 1)
                    rec["excess_1y"]  = round(_s20["follow_end"] - _s20["mkt_end"], 1)
                    # 綜合大盤組成（近12個月）：逐筆 benchmark 分組 + 各自窗內漲幅（供 hover 說明 blend）
                    _cnt = {}
                    for _c in _recent:
                        _bk = benchmark_for(_c.get("target"), _c.get("market"))
                        _cnt[_bk] = _cnt.get(_bk, 0) + 1
                    _bend = pd.Timestamp(config.BACKTEST_END)
                    _blend = []
                    for _tk, _n in sorted(_cnt.items(), key=lambda x: -x[1])[:6]:
                        _s = U["close"].get(_tk); _ret = None
                        if _s is not None and len(_s):
                            _p0 = _s.asof(_w0); _p1 = _s.asof(_bend)
                            if pd.notna(_p0) and pd.notna(_p1) and _p0:
                                _ret = round((_p1 / _p0 - 1) * 100, 1)
                        _blend.append({"tk": _tk, "n": _n, "ret": _ret})
                    rec["mkt_blend_1y"] = _blend
        # ── 一次 per-call 計分：方向命中（timing 型）＋ 贏大盤 hc（selection 型）──
        sc = per_call_scorecard(calls, U["close"], U["cal"], HOLDS)
        rec.update(sc["dir"])
        for _h, _c in sc["hc"].items():
            if _h in rec["horizons"]:
                rec["horizons"][_h]["hc"] = _c
        # 顯示用提示（非輸入分類）：由 call 組成推導——擇時(timing)筆數 > 選股(selection)筆數＝
        # 該人「多在賭方向」，前端據此決定主打哪個指標。純從資料浮現，不是人被貼標籤。
        _h20 = sc["hc"].get("20", {})
        _n_sel = sum(_h20.get(leg, {}).get(k, 0) for leg in ("long", "short")
                     for k in ("hit", "miss"))
        rec["is_market_bet"] = (sc["dir"]["n_direction_settled"] or 0) > _n_sel
        # 真實追蹤期間（用全量 calls，非 topbottom 截斷後的 call_results）：卡片副標＋排行榜顯示樣本厚度
        _cdates = sorted(str(c["date"])[:10] for c in calls if c.get("date"))
        if _cdates:
            rec["date_range"] = [_cdates[0], _cdates[-1]]
        # ── 逐筆底稿（八欄表；每筆 hit 依 target 自動判方向/贏大盤）──
        rec["call_results"] = build_call_results(
            calls, U["close"], U["cal"], mode=cfg.get("call_mode", "full"),
            rep_hold=20, horizons=HOLDS)
        # ── 追漲（喊買前後±20）：有個股 selection 看多 call 才有意義 ──
        if any(c.get("sign", 1) > 0 and not is_timing_call(c.get("target"), c.get("market"))
               for c in calls):
            ev = event_path(calls, U["close"], U["cal"])
            if ev:
                rec["event"] = ev
        # ── 配置層 Brinson：喊多個不同資產/市場（≥2 種 benchmark）才有意義（多資產擇時）──
        bset = {benchmark_for(c.get("target"), c.get("market")) for c in calls
                if c.get("target") and is_timing_call(c.get("target"), c.get("market"))}
        if len(bset) >= 2:
            al_ser = brinson_allocation(calls, U["ret"], U["cal"], U["cal_pos"], 20)
            if al_ser is not None:
                L = _leg(al_ser, pd.Series(True, index=al_ser.index))
                if L:
                    rec["allocation"] = {"excess_ann": L["excess_ann"], "t": L["t"],
                                         "n_weeks": L["n_weeks"]}
        cov = coverage(calls, U["close"]); rec["coverage"] = cov
        if cov["n_missing"]:
            cov_warn.append((name, cov))
        results[name] = rec

    # 缺價警告改由合併後的 results 重建（增量模式下沿用快取者的警告才不會消失）
    cov_warn = [(nm, rec["coverage"]) for nm, rec in results.items()
                if rec.get("coverage", {}).get("n_missing")]

    # ── Romano-Wolf stepdown 多重檢定：單一家族（人不分類）─────────────
    # 每個 (analyst,horizon) 的週超額＝「跟他 − 逐筆配對基準」，共同 null＝「無技能」，
    # 故全部進同一家族一起校正（控 FWER）。沿用 fdr_sig 鍵名供前端相容。
    raw_keys = {(a, h) for a, h, p in all_p if p < 0.05}
    rejected, _t = romano_wolf_reject(wk_series) if wk_series else (set(), {})
    rw_set = rejected
    fam = {
        "n_tests": len(wk_series),
        "n_raw_sig": sum(1 for k in wk_series if k in raw_keys),
        "n_fdr_sig": len(rejected),
        "method": "Romano-Wolf stepdown (B=5000, block=5w, α=0.05)",
    }
    families = {"全體（跟他 vs 逐筆配對基準）": fam}

    for a, rec in results.items():
        for h, st in rec.get("horizons", {}).items():
            st["fdr_sig"] = (a, h) in rw_set       # 語意：Romano-Wolf 存活
            st["raw_sig"] = (a, h) in raw_keys

    fdr_set = rw_set                                # 給結尾統計沿用
    meta = {
        "horizons": HOLDS,
        "families": families,
        # 向後相容：generate_site.py 仍讀這幾個鍵——全部指向單一家族（人不分類）。
        "kol_family": fam, "gooaye_family": fam, "dac_family": fam, "wu_family": fam,
        "method": (
            "逐筆判尺（人不分類）：每筆 call 的 benchmark=benchmark_for(target)——"
            "個股→該市場指數(TAIEX/SPY)、大盤/資產→自身；策略腿 praw=看多標的報酬"
            "(看空=現金)、基準腿=逐筆配對買進持有；週分批t；"
            "窗定義=resolve_span（開口日進場、裁切不丟、mark-to-market）；"
            "判決=Romano-Wolf stepdown（circular block bootstrap，控 FWER，單一家族）"
        ),
        "coverage_warnings": [
            {"analyst": nm, **cv} for nm, cv in cov_warn
        ],
    }

    m = len(all_p)
    raw_sig = sum(1 for _, _, p in all_p if p < 0.05)
    json.dump({"meta": meta, "analysts": results}, open(OUT, "w"), ensure_ascii=False, indent=2)
    pickle.dump({"results": results, "all_p": all_p, "wk_series": wk_series},
                open(STATE, "wb"))   # 供 --only 增量重算沿用

    print(f"共 {m} 次檢定｜原始 p<0.05：{raw_sig}｜運氣預期：{m*0.05:.1f}｜Romano-Wolf 存活：{len(fdr_set)}\n")
    print(f"{'分析師':<14}" + "".join(f"{str(h)+'日':>10}" for h in HOLDS))
    for a, d in results.items():
        row = f"{a:<14}"
        for h in HOLDS:
            st = d["horizons"].get(str(h))
            if st and st.get("excess_ann") is not None:
                mk  = "✓" if st["fdr_sig"] else ("*" if st["raw_sig"] else " ")
                row += f"{st['excess_ann']:>+8.0f}{mk} "
            elif st and st.get("short_excess_ann") is not None:
                row += f"{st['short_excess_ann']:>+7.0f}空 "   # 全看空型
            else:
                row += f"{'—':>10}"
        print(row)

    print(f"\n✓=FDR存活 *=原始顯著但FDR淘汰 → {OUT}")

    # ── 缺價稽核（把靜默跳過變成可見警告）──────────────────
    if cov_warn:
        print("\n⚠ 缺價警告（這些標的查無價格、已被引擎跳過，結果偏少）：")
        for nm, cv in cov_warn:
            ex = "、".join(cv["missing"][:8]) + ("…" if cv["n_missing"] > 8 else "")
            print(f"  {nm}：缺 {cv['n_missing']}/{cv['n_targets']} 檔，"
                  f"丟 {cv['n_calls_dropped']}/{cv['n_calls']} 筆 call → {ex}")
        print("  → 補價：python ensure_prices.py（補完重跑本檔）")
    else:
        print("\n✓ 價格覆蓋完整：所有標的皆有報價，無靜默跳過。")


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--only", default=None, help="只重算這位分析師（其他人沿用上次快取）")
    run(only=_ap.parse_args().only)
