"""
extract_decisions.py — 統一「決策抽取器」（喊單型/預言型/板塊型同一個 prompt）

統一管線第②步：LLM 讀任一逐字稿 → 一條條「決策」，不分析師類型。
  target_type   asset（商品/大盤）/ stock（個股）/ sector（板塊主題）
  target_name   他原文講的標的名（台積電 / 黃金 / 航運）
  direction     bullish / bearish
  date          宣告日（= 影片上傳日）
  T_start/T_end 若他講明時間窗（多無）→ explicit；否則 slice
  quote         原文代表句

輸出：data_cache/{slug}_decisions.json（每集一筆，含 decisions:[...]）。
沿用 extract_predictions 的 DeepSeek 呼叫 / JSON 清洗 / 增量續抓。

用法：
  from extract_decisions import extract_rows
  rows = extract_rows([{video_id,upload_date,title,transcript}], slug="kuo")
"""
from __future__ import annotations
import json, os, re, time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SYSTEM_PROMPT = """你是台股投資內容分析師，從投顧/財經影片字幕中抽取「可驗證的方向決策」。

作者可能點名個股、看好某板塊、或判斷某商品/大盤方向。逐一抽取他「明確表態看多或看空」的標的。

每筆決策輸出（JSON 陣列元素）：
- target_type: "stock"（點名個股，如台積電、長榮）/ "sector"（板塊或主題，如航運、半導體、AI、軍工）/ "asset"（商品或整體大盤，如黃金、比特幣、美股、台股大盤）
- target_name: 他原文講的名稱（個股給公司名或代碼；板塊給主題詞；商品給商品名）
- direction: "bullish"（看多/看好/叫買/逢低布局）/ "bearish"（看空/看壞/示警/該跑）
- timeframe_start: 若他講明時間（這週/這個月/下半年）估算開始 YYYY-MM-DD，否則填 null
- timeframe_end: 同上，否則 null
- quote: 原文代表句（≤50字）

規則（嚴格）：
✅ 只抽「對未來的建議/操作表態」：叫你買/賣、看好/看壞後市、逢低布局、該跑了、續抱、出清。
❌ 排除「陳述漲跌事實/報行情」——這不是決策：
   例「環球晶今天大漲9%」「長榮上漲接近半根停板」「台積電創新高」→ 不要抽（他只是在報它漲了，沒叫你做什麼）。
❌ 排除順口帶過、無方向、純技術名詞解釋、回顧已發生而無後續建議。
❌ 反諷/反向語氣要辨識真實意圖（嘴上酸其實看多 → bullish）。

判斷訣竅：問「他這句是在『報這檔漲跌了』還是『叫我對它做什麼』？」前者丟棄，後者才抽。
對照：
- 「南亞科今天噴漲停」→ 丟棄（陳述事實）
- 「南亞科拉回我要用力買」→ 抽（bullish，操作建議）
- 「廣達我今天逢高出掉」→ 抽（bearish，操作建議）

若整集無可抽取，回傳 {"decisions": []}。只輸出合法 JSON：{"decisions":[...]}。"""


def _client():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def extract_for_video(client, upload_date, title, transcript) -> list[dict]:
    text = transcript[:3000] if transcript else ""
    if len(text) < 100:
        return []
    user_msg = (f"影片上傳日期：{upload_date}\n影片標題：{title}\n\n字幕內容：\n{text}\n\n"
                f"請逐一標的抽取方向決策。")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat", temperature=0.1, max_tokens=2000,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_msg}])
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group() if m else raw)
        out = []
        for d in data.get("decisions", []):
            if d.get("target_type") in ("stock", "sector", "asset") \
               and d.get("direction") in ("bullish", "bearish") \
               and d.get("target_name"):
                out.append(d)
        return out
    except Exception as e:
        print(f"    LLM 錯誤: {e}")
        return []


def extract_rows(rows: list[dict], slug: str, force_refresh: bool = False) -> list[dict]:
    """rows: [{video_id,upload_date,title,transcript}] → data_cache/{slug}_decisions.json。"""
    pcache = Path(f"data_cache/{slug}_decisions.json")
    pcache.parent.mkdir(exist_ok=True)
    existing: dict[str, dict] = {}
    if pcache.exists() and not force_refresh:
        existing = {r["video_id"]: r for r in json.loads(pcache.read_text(encoding="utf-8"))}
        print(f"[{slug}] 已有快取：{len(existing)} 筆")

    client = _client()
    if client is None:
        print("❌ 缺少 DEEPSEEK_API_KEY"); return list(existing.values())

    usable = [r for r in rows if r.get("transcript") and len(r["transcript"]) > 200]
    print(f"[{slug}] 可抽影片：{len(usable)}（已完成 {len(existing)}）")
    results = list(existing.values())
    new = 0
    for i, r in enumerate(usable):
        vid = r["video_id"]
        if vid in existing:
            continue
        decs = extract_for_video(client, r["upload_date"], r.get("title", ""), r["transcript"])
        entry = {"video_id": vid, "upload_date": r["upload_date"],
                 "title": r.get("title", ""), "decisions": decs}
        results.append(entry); existing[vid] = entry; new += 1
        flag = f"📊 {len(decs)}" if decs else "（無）"
        print(f"  [{i+1}/{len(usable)}] {r['upload_date']} {flag} — {r.get('title','')[:36]}", flush=True)
        if new % 20 == 0:
            pcache.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.3)
    pcache.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(r["decisions"]) for r in results)
    print(f"\n[{slug}] 完成：新增 {new}，共 {total} 條決策 → {pcache}")
    return results


if __name__ == "__main__":
    import argparse, sqlite3, config
    p = argparse.ArgumentParser()
    p.add_argument("--channel-id", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--limit", type=int, default=0, help="0=全部")
    args = p.parse_args()
    conn = sqlite3.connect(config.STOCK_DB_PATH)
    q = ("SELECT video_id, upload_date, title, transcript FROM video_log "
         "WHERE channel_id=? AND transcript IS NOT NULL AND length(transcript)>200 "
         "ORDER BY upload_date DESC")
    rows = [{"video_id": a, "upload_date": b, "title": c, "transcript": d}
            for a, b, c, d in conn.execute(q, [args.channel_id]).fetchall()]
    conn.close()
    if args.limit:
        rows = rows[:args.limit]
    extract_rows(rows, args.slug)
