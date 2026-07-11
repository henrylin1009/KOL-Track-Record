"""
analysts.py — 分析師註冊表 + 各分析師的 Call loader

每位分析師的 loader 輸出統一格式 Call dict：
    target      : str         標的代碼 "2330" / "SPY"
    date        : str         宣告日 ISO "2024-04-01"
    sign        : int         +1 看多 / -1 看空
    T_start     : str|None    評估窗開始；None = slice
    T_end       : str|None    評估窗結束；None = slice；未來日期 = pending
    window_type : str         "explicit" | "scale" | "slice"

引擎只認 List[Call]，每位分析師的原生資料格式在此消化，不污染引擎。
"""
from __future__ import annotations
import json
import pandas as pd
import config

TODAY = pd.Timestamp.now().normalize()


def load_gooaye(cfg: dict | None = None) -> list[dict]:
    """
    載入股癌的 calls（全部 slice，無指定時間窗）。
    看多 sign=+1，看空 sign=-1（layer 3 記分用，非真放空）。
    """
    mapped = json.loads(open("data_cache/gooaye_themes_mapped.json", encoding="utf-8").read())
    calls, seen = [], set()
    for canon, v in mapped["themes"].items():
        inst = v["instrument"]
        for s in v["stances"]:
            sign = 1 if s["stance"] == "bullish" else -1
            key = (s["ep"], inst, sign)
            if key in seen:
                continue
            seen.add(key)
            _nm = f"{canon}（{inst}）"
            _ev = (s.get("evidence") or "").strip()
            calls.append(dict(
                target=inst,
                date=s["date"],
                sign=sign,
                T_start=None,
                T_end=None,
                window_type="slice",
                summary=_nm,                                 # 主題名（標的）
                full=f"{_nm}：{_ev}" if _ev else _nm,          # hover 顯示他原本怎麼說
            ))
    return calls


def load_dac(cfg: dict | None = None) -> list[dict]:
    """
    載入 DAC 的 calls。有 timeframe_end → explicit；否則 → slice。
    T_end 在未來 → pending（引擎跳過，不計入已結算統計）。
    """
    dac = json.loads(open("data_cache/dac_predictions.json", encoding="utf-8").read())
    calls, seen = [], set()
    for v in dac:
        upload = v.get("upload_date", "")
        ts = pd.to_datetime(upload, errors="coerce")
        if pd.isna(ts) or ts < pd.Timestamp("2020-03-01"):
            continue
        for p in v.get("predictions", []):
            d = p.get("direction")
            sign = 1 if d == "bullish" else (-1 if d in ("bearish", "crash") else 0)
            if sign == 0:
                continue
            t_start = p.get("timeframe_start") or upload
            t_end   = p.get("timeframe_end")
            wtype   = "explicit" if t_end else "slice"
            key = (upload, sign, t_start or "", t_end or "")
            if key in seen:
                continue
            seen.add(key)
            calls.append(dict(
                target="SPY",
                date=upload,
                sign=sign,
                T_start=t_start if wtype == "explicit" else None,
                T_end=t_end if wtype == "explicit" else None,
                window_type=wtype,
                summary="美股",   # 標準規則：格內顯示資產名（DAC 全喊美股大盤）
                full=(p.get("quote") or p.get("timeframe_desc") or "美股"),   # hover 顯示完整發言
            ))
    return calls


# 吳昌華 asset 標籤 → 價格代理 ticker
WU_ASSET_TICKER = {
    "us": "SPY", "crypto": "BTC-USD", "gold": "GLD", "hk": "EWH", "china": "FXI",
}


def load_wu(cfg: dict | None = None) -> list[dict]:
    """
    載入吳昌華（奇門遁甲命理派）多資產預言。
    每筆預言對某資產給方向，target = 該資產代理 ticker。
    有 timeframe_end → explicit；T_end 在未來 → pending（引擎跳過）。
    """
    path = "data_cache/wu_predictions.json"
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return []
    calls, seen = [], set()
    for v in data:
        upload = v.get("upload_date", "")
        ts = pd.to_datetime(upload, errors="coerce")
        if pd.isna(ts) or ts < pd.Timestamp("2020-03-01"):
            continue
        for p in v.get("predictions", []):
            asset = p.get("asset")
            target = WU_ASSET_TICKER.get(asset)
            if not target:
                continue
            d = p.get("direction")
            sign = 1 if d == "bullish" else (-1 if d == "bearish" else 0)
            if sign == 0:
                continue
            t_start = p.get("timeframe_start") or upload
            t_end   = p.get("timeframe_end")
            wtype   = "explicit" if t_end else "slice"
            key = (upload, target, sign, t_start or "", t_end or "")
            if key in seen:
                continue
            seen.add(key)
            ASSET_CN = {"us": "美股", "crypto": "比特幣", "gold": "黃金",
                        "hk": "港股", "china": "A股"}
            qfull = (p.get("quote") or "").strip()
            _pfx = ASSET_CN.get(asset, asset)
            calls.append(dict(
                target=target,
                date=upload,
                sign=sign,
                T_start=t_start if wtype == "explicit" else None,
                T_end=t_end if wtype == "explicit" else None,
                window_type=wtype,
                asset=asset,
                summary=_pfx,                                  # 格內只顯示資產名（簡潔）
                full=f"{_pfx}：{qfull}" if qfull else _pfx,     # hover 顯示完整發言
            ))
    return calls


def load_forecast(cfg: dict) -> list[dict]:
    """通用預言型 loader：讀 data_cache/{slug}_predictions.json（extract_predictions.py
    產出的多資產格式）→ Call dict。target = asset 對映 ticker（ASSET_TICKER）。
    有 timeframe_end → explicit 窗；T_end 在未來 → pending（引擎跳過）。
    add_analyst.py 註冊新預言型分析師即走此 loader，無須各寫一個。"""
    from extract_predictions import ASSET_TICKER, ASSET_CN
    slug = cfg.get("slug")
    if not slug:
        return []
    path = f"data_cache/{slug}_predictions.json"
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return []
    start = pd.Timestamp(cfg.get("start", "2020-03-01"))
    calls, seen = [], set()
    for v in data:
        upload = v.get("upload_date", "")
        ts = pd.to_datetime(upload, errors="coerce")
        if pd.isna(ts) or ts < start:
            continue
        for p in v.get("predictions", []):
            asset = p.get("asset")
            target = ASSET_TICKER.get(asset)
            if not target:
                continue
            d = p.get("direction")
            sign = 1 if d == "bullish" else (-1 if d == "bearish" else 0)
            if sign == 0:
                continue
            t_start = p.get("timeframe_start") or upload
            t_end   = p.get("timeframe_end")
            wtype   = "explicit" if t_end else "slice"
            key = (upload, target, sign, t_start or "", t_end or "")
            if key in seen:
                continue
            seen.add(key)
            qfull = (p.get("quote") or "").strip()
            _pfx = ASSET_CN.get(asset, asset)
            calls.append(dict(
                target=target, date=upload, sign=sign,
                T_start=t_start if wtype == "explicit" else None,
                T_end=t_end if wtype == "explicit" else None,
                window_type=wtype, asset=asset,
                summary=_pfx,                                  # 格內只顯示資產名（簡潔）
                full=f"{_pfx}：{qfull}" if qfull else _pfx,     # hover 顯示完整發言
            ))
    return calls


# 共用 Resolver（載入 tw_name_map 2520 支，貴，快取一次；引擎內不呼叫 LLM）
_RESOLVER = None
def _resolver():
    global _RESOLVER
    if _RESOLVER is None:
        from resolve_target import Resolver
        _RESOLVER = Resolver(use_llm_for_sector=False)
    return _RESOLVER


def load_decisions(cfg: dict) -> list[dict]:
    """★ 統一決策 loader（全遷後所有人走這條）：讀 data_cache/{slug}_decisions.json
    （extract_decisions 產出）→ resolve_target 把 target_name→代碼+市場 → Call dict。
    sector 展開成多支等權；call['market'] 帶市場標籤供 per-call 基準路由。
    引擎內不呼叫 LLM；未知板塊/查無代碼 → 略過（coverage 稽核會記）。
    同一影片內同股同向去重；跨影片保留（= call 頻率加權）。"""
    slug = cfg.get("slug")
    if not slug:
        return []
    path = f"data_cache/{slug}_decisions.json"
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return []
    start = pd.Timestamp(cfg.get("start", "2024-04-01"))
    r = _resolver()
    calls, seen = [], set()
    for v in data:
        upload = v.get("upload_date", "")
        ts = pd.to_datetime(upload, errors="coerce")
        if pd.isna(ts) or ts < start:
            continue
        d_iso = str(ts.date())
        for dec in v.get("decisions", []):
            codes, market, _src = r.resolve(dec.get("target_type"), dec.get("target_name"), date=d_iso)
            di = dec.get("direction")
            sign = 1 if di == "bullish" else (-1 if di == "bearish" else 0)
            if sign == 0 or not codes:
                continue
            for code in codes:
                key = (upload, code, sign)
                if key in seen:
                    continue
                seen.add(key)
                _nm = f'{dec.get("target_name")}（{code}）'
                _qt = (dec.get("quote") or "").strip()
                calls.append(dict(
                    target=code, date=d_iso, sign=sign,
                    T_start=None, T_end=None, window_type="slice",
                    market=market, summary=_nm,
                    full=f'{_nm}：{_qt}' if _qt else _nm,   # hover 顯示他原本怎麼說
                ))
    return calls


def kol_registry() -> dict:
    """全遷後 10 位 KOL 的統一註冊（走 load_decisions + tw 宇宙）。
    由 config.TARGET_CHANNELS 自動生成，slug 與 extract_all_kols 一致。"""
    return {c["name"]: dict(
        slug="kol_" + c["channel_id"][-8:],
        loader_key="decisions", universe="tw",
        market="台股", label="個股選股", is_market_bet=False,
        start="2024-04-01", call_mode="topbottom",
    ) for c in config.TARGET_CHANNELS}


# ── 分析師註冊表 ──────────────────────────────────────────────
# KOL 由 kol_registry() 依 config.TARGET_CHANNELS 自動生成（走 load_decisions）。
# 在此列的是「非 KOL」的個別分析師設定。
# universe = 價格宇宙鍵（引擎 run() 內建），決定報酬/日曆/benchmark 來源：
#   "us_etf" = ETF + SPY 基準（美股交易日）
#   "wu"     = 吳昌華五資產 + 等權籃基準
# 加新人：填一筆 dict（loader_key + universe + label/market/is_market_bet）即可，
# 引擎主迴圈自動跑，無須改 build_calendar_multi.py。family 由 (market,label) 自動推導。
ANALYSTS: dict[str, dict] = {
    "股癌（謝孟恭）": dict(
        loader_key="gooaye",
        universe="us_etf",
        benchmark="SPY",
        start="2020-03-01",
        label="個股選股",
        is_market_bet=False,
        market="美股",
    ),
    "鄭博見 DAC": dict(
        loader_key="dac",
        universe="us_etf",
        benchmark="SPY",
        start="2020-03-01",
        label="大盤擇時",
        is_market_bet=True,
        market="美股",
    ),
    "吳昌華": dict(
        loader_key="wu",
        universe="wu",
        benchmark="MATCHED",     # 逐筆對照「該資產自身買進持有」（B 版，只測擇時）
        matched_bench=True,      # ★ 每筆 call 的基準＝它自己那個資產的 buy-and-hold
        start="2020-03-01",
        label="大盤擇時",
        is_market_bet=True,
        market="多資產",   # 美股/比特幣/黃金/港股/A股；資產清單於卡片副標顯示
    ),
}


# loader_key → loader(cfg)
LOADERS = {
    "gooaye":   load_gooaye,
    "dac":      load_dac,
    "wu":       load_wu,
    "forecast": load_forecast,    # 通用預言型：吃 cfg['slug']
    "decisions": load_decisions,  # ★ 統一決策 loader（全遷後 KOL 走這條）
}


# ── 動態註冊表（add_analyst.py 自動寫入，免改本檔原始碼）──────────
# data_cache/analysts_registry.json：{name: {slug,loader_key,universe,market,label,is_market_bet,start}}
# 載入時合併進 ANALYSTS；引擎主迴圈一視同仁。
def _load_dynamic_registry() -> None:
    import os
    path = "data_cache/analysts_registry.json"
    if not os.path.exists(path):
        return
    try:
        reg = json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return
    for name, cfg in reg.items():
        ANALYSTS.setdefault(name, cfg)   # 既有手寫設定優先，不被覆寫


_load_dynamic_registry()
