"""對逐字稿跑 LLM 三維情緒評分，存入 stock_sentiment 表。

執行：
  python build_sentiment_stocks.py --months 3   # 最近 3 個月
  python build_sentiment_stocks.py --months 0   # 全量
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import date, datetime, timedelta

import config
from llm_scorer import score_stocks_in_transcript


# --------------------------------------------------------------------------
# DB 初始化
# --------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_sentiment (
            video_id    TEXT NOT NULL,
            stock_id    TEXT NOT NULL,
            upload_date TEXT,
            channel_id  TEXT,
            bullish     REAL,
            retail_mobilization REAL,
            emotion_intensity   REAL,
            mention_count       INTEGER,
            PRIMARY KEY (video_id, stock_id)
        )
    """)
    conn.commit()


def already_scored(conn: sqlite3.Connection, video_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM stock_sentiment WHERE video_id=? LIMIT 1", (video_id,)
    ).fetchone() is not None


def save_scores(conn, video_id, upload_date, channel_id, scores: dict):
    for stock_id, s in scores.items():
        conn.execute(
            "INSERT OR REPLACE INTO stock_sentiment VALUES (?,?,?,?,?,?,?,?)",
            (video_id, stock_id, upload_date, channel_id,
             s["bullish"], s["retail_mobilization"],
             s["emotion_intensity"], s["mention_count"])
        )
    conn.commit()


# --------------------------------------------------------------------------
# 主程式
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=3,
                        help="回溯幾個月（0=全量）")
    args = parser.parse_args()

    conn = sqlite3.connect(config.STOCK_DB_PATH)
    init_db(conn)

    # 決定起始日期
    if args.months > 0:
        since = (date.today() - timedelta(days=args.months * 30)).strftime("%Y%m%d")
    else:
        since = "20000101"

    rows = conn.execute(
        "SELECT video_id, channel_id, upload_date, title, transcript "
        "FROM video_log "
        "WHERE status='ok' AND transcript IS NOT NULL AND length(transcript) > 200 "
        "AND (upload_date >= ? OR upload_date IS NULL) "
        "ORDER BY upload_date DESC",
        (since,)
    ).fetchall()

    print(f"{'='*60}")
    print(f"個股 LLM 情緒評分")
    print(f"範圍: 最近 {args.months} 個月 ({since[:4]}-{since[4:6]}-{since[6:]}~)")
    print(f"待評分影片: {len(rows)} 部")
    print(f"{'='*60}\n")

    total_ok = total_skip = total_fail = 0

    for i, (video_id, channel_id, upload_date, title, transcript) in enumerate(rows):
        if already_scored(conn, video_id):
            total_skip += 1
            continue

        print(f"[{i+1}/{len(rows)}] {upload_date} {title[:45]}...", end=" ", flush=True)

        try:
            scores = score_stocks_in_transcript(transcript, config.STOCK_KEYWORDS)
            if scores:
                save_scores(conn, video_id, upload_date, channel_id, scores)
                stocks_hit = list(scores.keys())
                print(f"OK {stocks_hit}")
                total_ok += 1
            else:
                print("(無個股)")
                # 存一筆空記錄避免重複評分
                conn.execute(
                    "INSERT OR IGNORE INTO stock_sentiment VALUES (?,?,?,?,?,?,?,?)",
                    (video_id, "__none__", upload_date, channel_id, None, None, None, 0)
                )
                conn.commit()
                total_ok += 1
        except Exception as e:
            print(f"FAIL {e}")
            total_fail += 1

        time.sleep(0.3)  # 避免 API 限流

    conn.close()

    print(f"\n{'='*60}")
    print(f"完成  OK:{total_ok}  跳過:{total_skip}  失敗:{total_fail}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
