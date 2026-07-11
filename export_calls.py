"""
export_calls.py — 把引擎全量逐筆 call 攤平成一張表（給 AWS S3 + Athena SQL 用）。

唯讀：重用 build_calendar_multi 的函式與凍結價格池，不改引擎、不動 calendar_multi.json。
輸出：
  data_cache/calls_flat.csv       一列 = 一筆 call × 一個持有天期
  data_cache/calls_flat.parquet   同資料（Athena 查最省，優先上傳這個）

欄位：
  analyst, market, label        分析師 / 市場 / 型別標籤
  date                          喊盤日 YYYY-MM-DD
  ticker                        標的（summary，含代碼）
  direction                     看多 / 看空
  hold_days                     持有天期 5/20/60/120/250
  strat_ret / bench_ret / excess_ret   策略% / 對應大盤% / 超額%
  hit                           命中 / 未中 / pending
  is_pending                    是否未到期（True 時 hit=pending，不可當賺賠）
  period                        結算窗字串
"""
import csv
import glob
import json

import pandas as pd

import build_calendar_multi as bc
import analysts as ana
import config


def _build_pool_and_cals():
    """複製 run() 的凍結價格池 + 日曆設定（read-only，數字與正式建置一致）。"""
    data = pickle.load(open("full_price_cache.pkl", "rb"))
    taiex = data["taiex"]; taiex = taiex[~taiex.index.duplicated()].sort_index()
    prices = data["prices"]
    pxc = json.loads(open("data_cache/gooaye_predict_px.json", encoding="utf-8").read())
    etf_close = {}
    for t, d in pxc.items():
        s = pd.Series(d); s.index = pd.to_datetime(s.index); etf_close[t] = s.sort_index()
    _freeze = pd.Timestamp(config.BACKTEST_END)
    taiex = taiex[taiex.index <= _freeze]
    etf_close = {t: s[s.index <= _freeze] for t, s in etf_close.items()}
    spy = etf_close["SPY"]
    kol_close = {s: c[~c.index.duplicated()].sort_index() for s, c in prices.items()}
    kol_close = {s: c[c.index <= _freeze] for s, c in kol_close.items()}
    cal_tw = taiex.index[taiex.index >= bc.KOL_START]
    cal_tw_pos = {d: i for i, d in enumerate(cal_tw)}
    cal_us = spy.index[spy.index >= bc.GOOAYE_START]
    cal_us_pos = {d: i for i, d in enumerate(cal_us)}
    close_pool = dict(kol_close)
    close_pool["TAIEX"] = taiex
    for t, s in etf_close.items():
        close_pool.setdefault(t, s)
    for p in sorted(glob.glob("data_cache/*_px.json")):
        for t, d in json.loads(open(p, encoding="utf-8").read()).items():
            if t not in close_pool:
                s = pd.Series(d); s.index = pd.to_datetime(s.index)
                close_pool[t] = s.sort_index()[lambda x: x.index <= _freeze]
    CALS = {
        "tw": dict(close=close_pool, cal=cal_tw, cal_pos=cal_tw_pos),
        "us": dict(close=close_pool, cal=cal_us, cal_pos=cal_us_pos),
    }
    return CALS


import pickle  # noqa: E402 (放這裡避免頂部與 build 匯入衝突)


def main():
    CALS = _build_pool_and_cals()
    registry = {**ana.kol_registry(), **ana.ANALYSTS}
    home_of = lambda cfg: "tw" if cfg.get("market") == "台股" else "us"

    rows = []
    for name, cfg in registry.items():
        loader = ana.LOADERS.get(cfg["loader_key"])
        if loader is None:
            continue
        calls = loader(cfg) or []
        if not calls:
            continue
        U = CALS[home_of(cfg)]
        # mode="full" → 全量逐筆（非截斷的 top/bottom 10）
        crs = bc.build_call_results(calls, U["close"], U["cal"],
                                    mode="full", rep_hold=20, horizons=bc.HOLDS)
        for cr in crs:
            base = dict(analyst=name, market=cfg["market"], label=cfg["label"],
                        date=str(cr["date"])[:10], ticker=cr.get("summary", ""),
                        direction=cr.get("dir", ""))
            byh = cr.get("byh")
            if byh:  # slice 窗：每個天期一列
                for h, ev in byh.items():
                    rows.append({**base, "hold_days": int(h),
                                 "strat_ret": ev.get("strat"), "bench_ret": ev.get("bench"),
                                 "excess_ret": ev.get("excess"), "hit": ev.get("hit"),
                                 "is_pending": ev.get("hit") == "pending",
                                 "period": ev.get("period", "")})
            else:    # explicit 窗：單一列（天期記 None）
                rows.append({**base, "hold_days": None,
                             "strat_ret": cr.get("strat"), "bench_ret": cr.get("bench"),
                             "excess_ret": cr.get("excess"), "hit": cr.get("hit"),
                             "is_pending": cr.get("hit") == "pending",
                             "period": cr.get("period", "")})
        print(f"  {name:24} calls={len(calls):>5}  rows={sum(1 for r in rows if r['analyst']==name):>6}")

    cols = ["analyst", "market", "label", "date", "ticker", "direction",
            "hold_days", "strat_ret", "bench_ret", "excess_ret", "hit",
            "is_pending", "period"]
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv("data_cache/calls_flat.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    try:
        df.to_parquet("data_cache/calls_flat.parquet", index=False)
        pq = "data_cache/calls_flat.parquet ✅"
    except Exception as e:
        pq = f"parquet 失敗（{e}）——先用 CSV，需 pip install pyarrow"
    print(f"\n✅ 匯出 {len(df)} 列 / {df['analyst'].nunique()} 位分析師")
    print(f"   data_cache/calls_flat.csv")
    print(f"   {pq}")


if __name__ == "__main__":
    main()
