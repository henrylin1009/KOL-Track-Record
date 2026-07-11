"""用 yfinance 批次拉全台股還權調整收盤 + TAIEX，建立統一來源的價格快取。

優點：無 API 限額、還權調整、兩組同源（消除 survivorship 測試的數據源污染）。
輸出：full_price_cache.pkl（覆蓋，統一 yfinance 來源）
"""
import pickle, warnings
import pandas as pd
import yfinance as yf
import twstock
warnings.filterwarnings("ignore")

START, END = "2022-01-01", "2026-06-02"
BATCH = 100


def get_universe():
    codes = twstock.codes
    out = {}   # code -> yahoo_symbol
    for c, v in codes.items():
        if c.isdigit() and len(c) == 4 and v.type == "股票":
            out[c] = c + (".TW" if v.market == "上市" else ".TWO")
    return out


def main():
    uni = get_universe()
    syms = list(uni.values())
    code_of = {s: c for c, s in uni.items()}
    print(f"全台股 {len(syms)} 支，分 {len(syms)//BATCH+1} 批拉取…")

    prices, dollar_vol = {}, {}
    for i in range(0, len(syms), BATCH):
        chunk = syms[i:i + BATCH]
        df = yf.download(chunk, start=START, end=END, progress=False,
                         auto_adjust=True, group_by="ticker", threads=True)
        for s in chunk:
            try:
                d = df[s] if len(chunk) > 1 else df
                close = d["Close"].dropna()
                if len(close) > 150:
                    prices[code_of[s]] = close
                    # 日成交額（元）= 收盤 × 量，存中位數當流動性指標
                    dv = (d["Close"] * d["Volume"]).dropna()
                    dollar_vol[code_of[s]] = float(dv.median()) if len(dv) else 0.0
            except Exception:
                pass
        print(f"  {min(i+BATCH,len(syms))}/{len(syms)}  累計 {len(prices)}")

    # TAIEX
    tx = yf.download("^TWII", start=START, end=END, progress=False, auto_adjust=True)
    taiex = tx["Close"].dropna()
    taiex = taiex.squeeze() if hasattr(taiex, "squeeze") else taiex
    taiex.name = "price"

    pickle.dump({"taiex": taiex, "prices": prices, "dollar_vol": dollar_vol},
                open("full_price_cache.pkl", "wb"))
    print(f"完成：{len(prices)} 支 + TAIEX({len(taiex)}筆) + 流動性 → full_price_cache.pkl")


if __name__ == "__main__":
    main()
