"""
extract_predictions.py — 通用預言型抽取（泛化自 extract_wu/dac_predictions.py）

吃任一頻道的逐字稿快取 data_cache/{slug}_transcripts.json，用 DeepSeek 逐集抽取
「多資產方向預言」→ data_cache/{slug}_predictions.json。多資產 schema 為超集：
單市場作者（如 DAC 只談美股/全球）只會吐 us 子集，無妨。可被 add_analyst 程式呼叫。

每筆 prediction：
  asset           us/crypto/gold/hk/china/taiwan（對應下方 ASSET_TICKER）
  direction       bullish / bearish
  timeframe_desc  原文時間描述
  timeframe_start 估算開始 YYYY-MM-DD
  timeframe_end   估算結束 YYYY-MM-DD
  quote           原文代表句（≤60字）
  confidence      high / medium

用法：
  python extract_predictions.py --slug wu
  python extract_predictions.py --slug dac --refresh
程式呼叫：
  from extract_predictions import extract_channel
  rows = extract_channel("wu")
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# asset 標籤 → 價格代理 ticker（yfinance）。供通用 loader 共用。
ASSET_TICKER = {
    "us":     "SPY",      # 美股
    "crypto": "BTC-USD",  # 比特幣
    "gold":   "GLD",      # 黃金
    "hk":     "EWH",      # 港股
    "china":  "FXI",      # 中國 A股 / 中概
    "taiwan": "TAIEX",    # 台股大盤＝台灣加權指數（非美掛牌代理 EWT）；台灣分析師喊「大盤」就比 TAIEX
}
ASSET_CN = {"us": "美股", "crypto": "比特幣", "gold": "黃金",
            "hk": "港股", "china": "A股", "taiwan": "台股"}

SYSTEM_PROMPT = """你是金融研究助理，從財經影片字幕中提取可驗證的多資產方向預測。

作者可能每集對多個資產分別給「漲/跌」方向判斷。請逐一資產提取。

判斷標準：
✅ 納入：對某資產在某時段「會漲/會跌/偏多/偏空/震盪向上/向下」的方向判斷
✅ 納入：帶時間框架（本週、6月15-20日、這個月、下半年）的方向預測
❌ 排除：泛泛「注意風險」無明確方向
❌ 排除：回顧已發生（非預測）
❌ 排除：純命理/風水解讀但沒連到漲跌方向

資產分類（asset 欄位只能填這幾個）：
- "us"     美股（標普/道瓊/納斯達克/美國大盤/個股如英偉達特斯拉也算 us）
- "crypto" 比特幣/加密貨幣
- "gold"   黃金
- "hk"     港股/恒生
- "china"  中國股市/A股/上證/滬深
- "taiwan" 台股/台積電/加權指數

對每個資產×方向輸出 JSON：
- asset: 上述六類之一
- direction: "bullish"（看漲/偏多）/ "bearish"（看跌/偏空）
- timeframe_desc: 原文時間描述
- timeframe_start: 估算開始 YYYY-MM-DD（以影片上傳日與標題日期為基準）
- timeframe_end: 估算結束 YYYY-MM-DD
- quote: 原文代表句（≤60字）
- confidence: "high"（語氣肯定）/ "medium"

若震盪/中性無明確方向，該資產略過。若整集無可用預測，回傳 {"predictions": []}。
只輸出合法 JSON。"""


def extract_for_video(client, upload_date, title, transcript) -> list[dict]:
    text = transcript[:2600] if transcript else ""
    if len(text) < 100:
        return []
    user_msg = (f"影片上傳日期：{upload_date}\n影片標題：{title}\n\n字幕內容：\n{text}\n\n"
                f"請逐一資產提取方向預測。標題常含明確日期區間，優先採用。")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_msg}],
            temperature=0.1, max_tokens=1800,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        preds = data.get("predictions", [])
        return [p for p in preds if p.get("asset") in ASSET_TICKER
                and p.get("direction") in ("bullish", "bearish")]
    except Exception as e:
        print(f"    LLM 錯誤: {e}")
        return []


def extract_channel(slug: str, force_refresh: bool = False) -> list[dict]:
    """讀 {slug}_transcripts.json → 抽預言 → {slug}_predictions.json。回傳 rows。"""
    tcache = Path(f"data_cache/{slug}_transcripts.json")
    pcache = Path(f"data_cache/{slug}_predictions.json")
    if not tcache.exists():
        print(f"❌ 找不到 {tcache}，請先跑 fetch_transcripts.py --slug {slug}")
        return []
    transcripts = json.loads(tcache.read_text())
    with_sub = [r for r in transcripts if r.get("has_subtitle") and r.get("transcript")]
    print(f"[{slug}] 有字幕影片：{len(with_sub)} / {len(transcripts)}")

    existing: dict[str, dict] = {}
    if pcache.exists() and not force_refresh:
        existing = {r["video_id"]: r for r in json.loads(pcache.read_text())}
        print(f"已有快取：{len(existing)} 筆")

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 缺少 DEEPSEEK_API_KEY"); return list(existing.values())
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    results = list(existing.values())
    new_count = 0
    for i, r in enumerate(with_sub):
        vid = r["video_id"]
        if vid in existing:
            continue
        preds = extract_for_video(client, r["upload_date"], r["title"], r["transcript"])
        entry = {"video_id": vid, "upload_date": r["upload_date"],
                 "title": r["title"], "predictions": preds}
        results.append(entry); existing[vid] = entry; new_count += 1
        flag = f"📊 {len(preds)} 條" if preds else "（無）"
        print(f"  [{i+1}/{len(with_sub)}] {r['upload_date']} {flag} — {r['title'][:40]}")
        if new_count % 10 == 0:
            pcache.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        time.sleep(0.4)
    pcache.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    total = sum(len(r["predictions"]) for r in results)
    print(f"\n完成：新增 {new_count} 筆，共 {total} 條預測 → {pcache}")
    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True, help="逐字稿快取片段（data_cache/{slug}_transcripts.json）")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    extract_channel(args.slug, force_refresh=args.refresh)
