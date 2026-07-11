"""掃描所有逐字稿，統計被點名的個股 universe。

用 FinMind 查詢上市/上櫃股票清單，對每支股票建立關鍵字（公司簡稱），
然後掃過 4,625 部逐字稿，統計每支股票被點名的頻率。

輸出：
  1. 終端機印出被點名次數排行
  2. stock_universe.csv — 供後續擴池用
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict

import pandas as pd

import config
from data_loader import TWDataLoader


# --------------------------------------------------------------------------
# 1. 取得上市/上櫃股票清單（用 FinMind）
# --------------------------------------------------------------------------

def fetch_listed_stocks(dl: TWDataLoader) -> pd.DataFrame:
    """回傳 DataFrame(stock_id, name)，只保留普通股（去掉 ETF、權證等）。"""
    try:
        # FinMind TaiwanStockInfo
        df = dl.dl.taiwan_stock_info()
        if df is None or df.empty:
            print("  [WARN] FinMind 股票清單為空，改用本地備援")
            return pd.DataFrame()
        # 只保留上市/上櫃普通股（stock_id 為 4 位數字）
        df = df[df["stock_id"].str.match(r"^\d{4}$")].copy()
        df = df[["stock_id", "stock_name"]].rename(columns={"stock_name": "name"})
        print(f"  取得 {len(df)} 支上市/上櫃股票")
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"  [WARN] FinMind 股票清單失敗: {e}")
        return pd.DataFrame()


# --------------------------------------------------------------------------
# 2. 建立個股關鍵字（公司簡稱）
# --------------------------------------------------------------------------

def build_keywords(df: pd.DataFrame) -> dict[str, list[str]]:
    """從股票名稱提取關鍵字（移除常見後綴）。"""
    suffixes = ["股份有限公司", "有限公司", "控股", "投控", "科技", "電子",
                "半導體", "工業", "實業", "集團", "國際", "企業"]
    result = {}
    for _, row in df.iterrows():
        sid = row["stock_id"]
        name = row["name"]
        short = name
        for s in suffixes:
            short = short.replace(s, "")
        short = short.strip()
        if len(short) >= 2:  # 太短的忽略（避免單字誤匹配）
            result[sid] = [short, name] if short != name else [name]
    return result


# --------------------------------------------------------------------------
# 3. 掃描逐字稿
# --------------------------------------------------------------------------

def scan_transcripts(keywords: dict[str, list[str]]) -> dict[str, dict]:
    """掃描所有逐字稿，回傳每支股票的統計。"""
    conn = sqlite3.connect(config.STOCK_DB_PATH)
    rows = conn.execute(
        "SELECT video_id, channel_id, upload_date, transcript "
        "FROM video_log WHERE status='ok' AND transcript IS NOT NULL AND length(transcript) > 100"
    ).fetchall()
    conn.close()

    print(f"\n掃描 {len(rows)} 部逐字稿...")

    # 預編譯 regex（速度快很多）
    patterns = {
        sid: re.compile("|".join(re.escape(kw) for kw in kws))
        for sid, kws in keywords.items()
        if kws
    }

    stats: dict[str, dict] = defaultdict(lambda: {
        "video_count": 0,       # 被點名的影片數
        "total_mentions": 0,    # 總提到次數
        "channels": set(),      # 哪些頻道提到過
        "weeks": set(),         # 哪些週提到過
    })

    for i, (vid, ch_id, upload_date, transcript) in enumerate(rows):
        if i % 500 == 0:
            print(f"  [{i}/{len(rows)}] 處理中...")

        week = upload_date[:6] if upload_date else "unknown"

        for sid, pat in patterns.items():
            matches = pat.findall(transcript)
            if matches:
                stats[sid]["video_count"] += 1
                stats[sid]["total_mentions"] += len(matches)
                stats[sid]["channels"].add(ch_id)
                stats[sid]["weeks"].add(week)

    return dict(stats)


# --------------------------------------------------------------------------
# 4. 輸出
# --------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("個股 Universe 掃描")
    print("=" * 60)

    dl = TWDataLoader()

    print("\n[1/3] 取得股票清單...")
    listed = fetch_listed_stocks(dl)
    if listed.empty:
        print("  失敗，使用現有 STOCK_KEYWORDS 作備援")
        # 備援：用 config 裡的 21 支
        listed = pd.DataFrame([
            {"stock_id": k, "name": v[0]} for k, v in config.STOCK_KEYWORDS.items()
        ])

    print("\n[2/3] 建立關鍵字...")
    keywords = build_keywords(listed)
    # 把 config.STOCK_KEYWORDS 的自訂關鍵字也加進去（包含英文名稱）
    for sid, kws in config.STOCK_KEYWORDS.items():
        if sid in keywords:
            keywords[sid] = list(set(keywords[sid] + kws))
        else:
            keywords[sid] = kws
    print(f"  建立 {len(keywords)} 支股票的關鍵字")

    print("\n[3/3] 掃描逐字稿...")
    stats = scan_transcripts(keywords)

    # 整理成 DataFrame
    name_map = dict(zip(listed["stock_id"], listed["name"]))
    rows_out = []
    for sid, s in stats.items():
        rows_out.append({
            "stock_id": sid,
            "name": name_map.get(sid, ""),
            "video_count": s["video_count"],
            "total_mentions": s["total_mentions"],
            "n_channels": len(s["channels"]),
            "n_weeks": len(s["weeks"]),
            "mention_rate": round(s["video_count"] / 4625, 3),  # 佔總影片比
        })

    df_out = pd.DataFrame(rows_out).sort_values("video_count", ascending=False)

    print(f"\n=== 被點名股票：{len(df_out)} 支 ===")
    print(f"\nTop 50（依影片數排序）：")
    print(df_out.head(50).to_string(index=False))

    print(f"\n影片數 ≥ 50 的股票：{(df_out['video_count'] >= 50).sum()} 支")
    print(f"影片數 ≥ 20 的股票：{(df_out['video_count'] >= 20).sum()} 支")
    print(f"影片數 ≥ 10 的股票：{(df_out['video_count'] >= 10).sum()} 支")

    df_out.to_csv("stock_universe.csv", index=False, encoding="utf-8-sig")
    print(f"\n已存：stock_universe.csv")


if __name__ == "__main__":
    main()
