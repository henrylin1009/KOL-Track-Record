"""
backfill_delisted.py — 修漏洞二（survivorship）：把 KOL 喊過但快取缺的股票
（多為下市股）用 FinMind 原始價補進 full_price_cache.pkl。

FinMind 免費版有下市股原始價（無還權）；對下市地雷而言，抓回崩盤遠比配息精度重要。
原檔先備份 full_price_cache.pkl.bak。
"""
from __future__ import annotations
import pickle, sqlite3, time, shutil
import requests
import pandas as pd
import config

CACHE = "full_price_cache.pkl"
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def finmind_close(sid: str, start="2018-01-01", end="2026-06-13"):
    r = requests.get(FINMIND, params={"dataset": "TaiwanStockPrice", "data_id": sid,
                                      "start_date": start, "end_date": end}, timeout=40)
    data = r.json().get("data", [])
    if not data:
        return None
    s = pd.Series({pd.Timestamp(d["date"]): d["close"] for d in data
                   if d.get("close") and d["close"] > 0}).sort_index()
    return s if len(s) > 5 else None


def run():
    d = pickle.load(open(CACHE, "rb"))
    cached = set(d["prices"].keys())
    conn = sqlite3.connect(config.STOCK_DB_PATH)
    mentioned = set(r[0] for r in conn.execute(
        "SELECT DISTINCT stock_id FROM stock_sentiment WHERE stock_id!='__none__'").fetchall())
    conn.close()
    missing = sorted(s for s in mentioned if s not in cached)
    print(f"缺漏 {len(missing)} 支，開始從 FinMind 補原始價…")

    shutil.copy(CACHE, CACHE + ".bak")
    added, failed = 0, []
    for sid in missing:
        s = finmind_close(sid)
        if s is None:
            failed.append(sid); print(f"  ✗ {sid} 無資料"); time.sleep(0.4); continue
        d["prices"][sid] = s
        added += 1
        print(f"  ✓ {sid} {len(s)} 日（{s.index[0].date()}~{s.index[-1].date()}）")
        time.sleep(0.4)

    pickle.dump(d, open(CACHE, "wb"))
    print(f"\n補進 {added} 支，失敗 {len(failed)}：{failed}")
    print(f"快取現有 {len(d['prices'])} 支 → {CACHE}（原檔備份 {CACHE}.bak）")


if __name__ == "__main__":
    run()
