"""
ensure_prices.py — 自動補價：把引擎「查無價格、靜默跳過」的標的抓回快取。

來源：讀 calendar_multi.json 的 meta.coverage_warnings（build_calendar_multi.py
產生的缺價清單），逐一用 yfinance 補抓，寫回對應快取：
  台股 4 碼數字 → full_price_cache.pkl["prices"][code]（.TW→.TWO 後援）
  其他（美股/ETF/幣/金代碼）→ 指定 json 快取（預設 gooaye_predict_px.json）

用法：
  python ensure_prices.py                      # 補所有缺價（台股自動、外股進 ETF 快取）
  python ensure_prices.py --foreign-cache data_cache/wu_px.json   # 外股改寫吳的快取
  python ensure_prices.py 2315 3584            # 只補指定代碼（不讀警告檔）

補完後重跑 `python build_calendar_multi.py`，缺價警告應消失或縮小。
"""
from __future__ import annotations
import argparse, json, pickle, sys, warnings
from pathlib import Path
import pandas as pd
import yfinance as yf
warnings.filterwarnings("ignore")

import config
START, END = "2019-01-01", config.BACKTEST_END   # 末日凍結：補價不得超過 BACKTEST_END，
# 否則「今天跑更新」會延長既有 call 的 mark-to-market 窗、連帶改動別人的數字（回歸會擋）
PKL = "full_price_cache.pkl"
CM  = "calendar_multi.json"


def _is_tw(code: str) -> bool:
    return code.isdigit() and len(code) == 4


YF_ALIAS = {"TAIEX": "^TWII"}   # 本地代號 → Yahoo 代號（台灣加權指數）；引擎池另有本地 TAIEX 序列


def _fetch(symbol: str) -> pd.Series | None:
    try:
        df = yf.download(YF_ALIAS.get(symbol, symbol), start=START, end=END, progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df["Close"].dropna()
        close = close.squeeze() if hasattr(close, "squeeze") else close
        return close if len(close) > 50 else None
    except Exception:
        return None


def fetch_tw(code: str) -> pd.Series | None:
    """台股先試 .TW（上市）再試 .TWO（上櫃）。"""
    for suf in (".TW", ".TWO"):
        s = _fetch(code + suf)
        if s is not None:
            return s
    return None


def build_px_cache(tickers: set[str], slug: str) -> int:
    """抓一組 ticker（ETF/幣/金/指數代理）→ data_cache/{slug}_px.json。
    供預言型分析師的價格宇宙用（add_analyst 自動呼叫）。回傳成功檔數。"""
    p = Path(f"data_cache/{slug}_px.json")
    px = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    added = 0
    for t in sorted(tickers):
        if t in px:
            continue
        s = _fetch(t)
        if s is not None:
            px[t] = {str(d.date()): round(float(v), 6) for d, v in s.items()}
            added += 1
            print(f"  ✓ {t}：{len(s)} 筆")
        else:
            print(f"  ✗ {t}：yfinance 查無")
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(px, ensure_ascii=False), encoding="utf-8")
    print(f"  → {p}（共 {len(px)} 檔）")
    return added


def missing_from_warnings() -> tuple[set[str], set[str]]:
    """讀 coverage_warnings → (台股缺碼集合, 外股缺碼集合)。"""
    try:
        meta = json.load(open(CM, encoding="utf-8"))["meta"]
    except FileNotFoundError:
        sys.exit(f"找不到 {CM}，請先跑 build_calendar_multi.py")
    tw, foreign = set(), set()
    for w in meta.get("coverage_warnings", []):
        for t in w.get("missing", []):
            (tw if _is_tw(t) else foreign).add(t)
    return tw, foreign


def backfill_tw(codes: set[str]) -> int:
    if not codes:
        return 0
    data = pickle.load(open(PKL, "rb"))
    prices = data["prices"]
    added = 0
    for c in sorted(codes):
        if c in prices:
            continue
        s = fetch_tw(c)
        if s is not None:
            s.name = c
            prices[c] = s
            added += 1
            print(f"  ✓ 台股 {c}：{len(s)} 筆 → full_price_cache.pkl")
        else:
            print(f"  ✗ 台股 {c}：yfinance 查無（可能已下市且 Yahoo 已砍歷史）")
    if added:
        Path(PKL).rename(PKL + ".bak")
        pickle.dump(data, open(PKL, "wb"))
        print(f"  已更新 {PKL}（舊檔備份 {PKL}.bak）")
    return added


def backfill_foreign(tickers: set[str], cache_path: str) -> int:
    if not tickers:
        return 0
    p = Path(cache_path)
    px = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    added = 0
    for t in sorted(tickers):
        if t in px:
            continue
        s = _fetch(t)
        if s is not None:
            px[t] = {str(d.date()): round(float(v), 6) for d, v in s.items()}
            added += 1
            print(f"  ✓ 外股 {t}：{len(s)} 筆 → {cache_path}")
        else:
            print(f"  ✗ 外股 {t}：yfinance 查無")
    if added:
        p.write_text(json.dumps(px, ensure_ascii=False), encoding="utf-8")
        print(f"  已更新 {cache_path}")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", help="只補指定代碼（省略則讀 coverage_warnings）")
    ap.add_argument("--foreign-cache", default="data_cache/gooaye_predict_px.json",
                    help="外股寫入的 json 快取（預設 ETF 快取）")
    args = ap.parse_args()

    if args.codes:
        tw = {c for c in args.codes if _is_tw(c)}
        foreign = {c for c in args.codes if not _is_tw(c)}
    else:
        tw, foreign = missing_from_warnings()

    if not tw and not foreign:
        print("✓ 無缺價標的，無須補抓。")
        return

    print(f"補價：台股 {len(tw)} 檔、外股 {len(foreign)} 檔…")
    n1 = backfill_tw(tw)
    n2 = backfill_foreign(foreign, args.foreign_cache)
    print(f"\n完成：新增 {n1+n2} 檔。→ 重跑 python build_calendar_multi.py 確認警告消失。")


if __name__ == "__main__":
    main()
