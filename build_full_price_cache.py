"""拉「從未被 KOL 提過」的股票價格，併入現有快取 → 全宇宙版（堵 survivorship）。"""
import pickle, re
import pandas as pd
import config
from data_loader import TWDataLoader

OUT = "full_price_cache.pkl"


def main():
    dl = TWDataLoader()
    dl.max_retries = 1          # 下市股票直接跳過，不要 15 秒 retry
    info = dl.dl.taiwan_stock_info()
    info = info[info["stock_id"].str.match(r"^\d{4}$")]
    all_ids = sorted(set(info["stock_id"].unique()))

    import random
    base = pickle.load(open("price_cache.pkl", "rb"))
    prices = dict(base["prices"])          # 已含被提過的 487
    taiex = base["taiex"]
    have = set(prices.keys())
    never = [s for s in all_ids if s not in have]
    random.seed(42)
    random.shuffle(never)
    SAMPLE = 700                            # 隨機抽樣（避免燒爆 API 限額）
    todo = never[:SAMPLE]
    print(f"全台股 {len(all_ids)}，已有 {len(have)}，從未被提 {len(never)}，本次抽樣拉 {len(todo)}")

    for i, sid in enumerate(todo):
        try:
            px = dl.stock_daily(sid, "2022-01-01", config.BACKTEST_END)
            if px is not None and not px.empty:
                s = px.assign(date=pd.to_datetime(px["date"])).set_index("date").sort_index()["close"]
                if len(s) > 150:
                    prices[sid] = s
        except Exception:
            pass
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(todo)}  總計 {len(prices)}")

    pickle.dump({"taiex": taiex, "prices": prices}, open(OUT, "wb"))
    print(f"完成：全宇宙 {len(prices)} 支 → {OUT}")


if __name__ == "__main__":
    main()
