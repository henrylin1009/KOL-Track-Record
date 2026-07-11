"""
ask_query.py — 階段一「查決策事實」的下層純查詢引擎（零 LLM）。

方法：Text-to-Query / Tool-Augmented（不是向量 RAG）。
本檔只做一件事：給定 分析師 / 標的 / 方向 / 日期區間 / 持有天數，
從 {slug}_decisions.json 撈出對應的 call，並用【引擎本身的 _fwd_ret】
算出每筆的「策略報酬 vs 大盤 vs 超額」。

★ 誠實界線：所有數字都由這裡的 Python 算，LLM 一律不碰計算。
  查無價格 / 未到期 → 誠實回 pending / no_price，絕不編。
"""
from __future__ import annotations
import pickle
import pandas as pd

import config
import analysts as ana
import build_calendar_multi as eng  # 重用 _fwd_ret / 常數 / universe 組法


# ── 價格宇宙（一次載入，之後查詢共用）────────────────────────────
_UNIVERSES: dict | None = None
_REGISTRY: dict | None = None


def _boot():
    """載入 full_price_cache + 建 tw / us_etf 宇宙 + 註冊表。與 eng.run() 同源。"""
    global _UNIVERSES, _REGISTRY
    if _UNIVERSES is not None:
        return
    data = pickle.load(open("full_price_cache.pkl", "rb"))
    taiex = data["taiex"]; taiex = taiex[~taiex.index.duplicated()].sort_index()
    prices = data["prices"]

    pxc = __import__("json").load(open("data_cache/gooaye_predict_px.json", encoding="utf-8"))
    etf_close = {t: pd.Series(d).pipe(lambda s: s.set_axis(pd.to_datetime(s.index)).sort_index())
                 for t, d in pxc.items()}
    spy = etf_close["SPY"]

    kol_close = {s: c[~c.index.duplicated()].sort_index() for s, c in prices.items()}

    _UNIVERSES = {
        "tw": dict(close=kol_close, bench_close=taiex,
                   cal=taiex.index[taiex.index >= eng.KOL_START], default_target=None),
        "us_etf": dict(close=etf_close, bench_close=spy,
                       cal=spy.index[spy.index >= eng.GOOAYE_START], default_target="SPY"),
    }
    _REGISTRY = {**ana.kol_registry(), **ana.ANALYSTS}


def list_analysts() -> list[dict]:
    """回傳所有分析師：{name, market, label}。給 LLM 當「可查名單」用。"""
    _boot()
    return [dict(name=n, market=c["market"], label=c["label"]) for n, c in _REGISTRY.items()]


def list_targets(analyst: str, top: int = 30) -> dict:
    """回傳某分析師實際喊過的標的清單（依喊單次數排序）。
    給 LLM 用來「只推薦真的查得到的標的」，避免建議不存在的代碼。"""
    _boot()
    if analyst not in _REGISTRY:
        return {"found": False, "error": f"查無此分析師：{analyst}"}
    cfg = _REGISTRY[analyst]
    loader = ana.LOADERS.get(cfg["loader_key"])
    calls = loader(cfg) if loader else []
    from collections import Counter
    cnt = Counter()
    label = {}
    for c in calls:
        t = c.get("target")
        cnt[t] += 1
        label.setdefault(t, c.get("summary", ""))
    items = [{"target": t, "n_calls": n, "example": label.get(t, "")}
             for t, n in cnt.most_common(top)]
    return {"found": True, "analyst": analyst, "n_targets": len(cnt), "targets": items}


def _universe_for(cfg: dict) -> dict | None:
    key = cfg["universe"]
    if key in _UNIVERSES:
        return _UNIVERSES[key]
    path = f"data_cache/{key}_px.json"  # 多資產預言型（吳昌華等）動態建
    try:
        U = eng.build_px_universe(path)
    except FileNotFoundError:
        return None
    _UNIVERSES[key] = dict(close=U["close"], bench_close=U["bench_close"],
                           cal=U["cal"], default_target=U["default_target"])
    return _UNIVERSES[key]


def query_calls(analyst: str, ticker: str | None = None, direction: str | None = None,
                start: str | None = None, end: str | None = None, hold: int = 20,
                group_by: str | None = None) -> dict:
    """★ 這就是 LLM 會呼叫的工具。

    參數：
      analyst   分析師姓名（需在 list_analysts() 內，精確比對）
      ticker    標的關鍵字（比對 summary，如 "台積" / "環球晶" / "SPY"）；None = 全部
      direction "bullish" / "bearish"；None = 不限
      start,end "YYYY-MM-DD" 日期區間；None = 不限
      hold      持有天數（5/20/60/120/250 之一，預設 20）
      group_by  "month"/"quarter"/"year"；給了就【由引擎】算分組摘要（模型不必自己數）

    回傳（全部由引擎算，可直接朗讀）：
      {found, analyst, hold,
       summary: {n, n_win, win_rate, avg_excess_pct, avg_strat_pct, avg_bench_pct, n_pending},
       calls: [{date, target, direction, quote, strat_pct, bench_pct, excess_pct, outcome}],
       groups: [{period, n, n_win, win_rate, avg_excess_pct}]  # group_by 有給才出現}
    """
    _boot()
    if analyst not in _REGISTRY:
        return {"found": False, "error": f"查無此分析師：{analyst}",
                "hint": "請用 list_analysts 內的精確姓名"}
    cfg = _REGISTRY[analyst]
    U = _universe_for(cfg)
    if U is None:
        return {"found": False, "error": f"{analyst} 的價格宇宙不可用"}

    loader = ana.LOADERS.get(cfg["loader_key"])
    calls = loader(cfg) if loader else []

    s_ts = pd.Timestamp(start) if start else None
    e_ts = pd.Timestamp(end) if end else None
    cal = U["cal"]; bench = U["bench_close"]

    rows, n_win = [], 0
    tot_ex = tot_st = tot_bh = 0.0
    n_scored = n_pending = 0
    for c in calls:
        cts = pd.Timestamp(c["date"])
        if s_ts is not None and cts < s_ts:  continue
        if e_ts is not None and cts > e_ts:  continue
        sign = c.get("sign", 1)
        if direction == "bullish" and sign <= 0:  continue
        if direction == "bearish" and sign >= 0:  continue
        summ = c.get("summary", "")
        if ticker and ticker not in summ and ticker != c.get("target"):  continue

        close = U["close"].get(c.get("target", U["default_target"]))
        if close is None:
            rows.append(_row(c, sign, None, None, None, "no_price")); continue
        pos = cal.searchsorted(cts)
        if pos + hold >= len(cal):
            rows.append(_row(c, sign, None, None, None, "pending")); n_pending += 1; continue
        t1 = cal[pos + hold]
        a = eng._fwd_ret(close, cts, t1)
        b = eng._fwd_ret(bench, cts, t1)
        if a is None or b is None:
            rows.append(_row(c, sign, None, None, None, "no_price")); continue
        strat = a if sign > 0 else -a          # 看空 → 賺跌幅
        excess = (a - b) if sign > 0 else (b - a)
        win = excess > 0
        n_win += win; n_scored += 1
        tot_ex += excess; tot_st += strat; tot_bh += b
        rows.append(_row(c, sign, strat, b, excess, "win" if win else "lose"))

    summary = dict(
        n=len(rows), n_scored=n_scored, n_win=n_win, n_pending=n_pending,
        win_rate=round(n_win / n_scored, 3) if n_scored else None,
        avg_excess_pct=round(100 * tot_ex / n_scored, 2) if n_scored else None,
        avg_strat_pct=round(100 * tot_st / n_scored, 2) if n_scored else None,
        avg_bench_pct=round(100 * tot_bh / n_scored, 2) if n_scored else None,
    )
    out = {"found": True, "analyst": analyst, "hold": hold,
           "summary": summary, "calls": rows}
    if group_by:
        out["groups"] = _group_rows(rows, group_by)
    return out


def _group_rows(rows, group_by):
    """★ 由引擎算分組摘要（模型禁止自己數）。只統計已結算(win/lose)的筆。"""
    def key(date):
        ts = pd.Timestamp(date)
        if group_by == "year":    return str(ts.year)
        if group_by == "quarter": return f"{ts.year}Q{(ts.month - 1)//3 + 1}"
        return f"{ts.year}-{ts.month:02d}"          # 預設 month
    buckets = {}
    for r in rows:
        if r["outcome"] not in ("win", "lose"):     # pending/no_price 不計入統計
            continue
        b = buckets.setdefault(key(r["date"]),
                               {"n": 0, "n_win": 0, "sum_ex": 0.0})
        b["n"] += 1
        b["n_win"] += (r["outcome"] == "win")
        b["sum_ex"] += r["excess_pct"]
    return [{"period": p, "n": b["n"], "n_win": b["n_win"],
             "win_rate": round(b["n_win"] / b["n"], 3),
             "avg_excess_pct": round(b["sum_ex"] / b["n"], 2)}
            for p, b in sorted(buckets.items())]


def _row(c, sign, strat, bench, excess, outcome):
    return dict(
        date=c["date"], target=c.get("target"),
        direction="看多" if sign > 0 else "看空",
        quote=c.get("summary", ""),
        strat_pct=None if strat is None else round(100 * strat, 2),
        bench_pct=None if bench is None else round(100 * bench, 2),
        excess_pct=None if excess is None else round(100 * excess, 2),
        outcome=outcome,
    )


if __name__ == "__main__":
    # 手動 smoke test（不經 LLM）
    import json, sys
    print("分析師名單：")
    for a in list_analysts():
        print("  ", a["name"], "|", a["market"], "|", a["label"])
    who = sys.argv[1] if len(sys.argv) > 1 else "郭哲榮"
    kw = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"\n查詢 {who} / {kw} / hold=20：")
    print(json.dumps(query_calls(who, ticker=kw, hold=20), ensure_ascii=False, indent=1))
