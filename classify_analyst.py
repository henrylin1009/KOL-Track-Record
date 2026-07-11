"""
classify_analyst.py — 判型器（公正閘門A）：call（喊單型）vs forecast（預言型）

輸入頻道標題樣本（+ 可選一份逐字稿樣本）→ LLM 判型 + 信心 + 理由。
全自動、不暫停；理由與信心寫入審計卡供事後覆核。

型別定義：
  call     喊單型：點名個股/產業要買/看好（多無明確到期日）
  forecast 預言型：賭某資產/大盤未來方向（多帶時間窗，如某月、某週）

用法：
  from classify_analyst import classify
  r = classify(titles, sample_text)   # → {"type","confidence","reason"}
"""
from __future__ import annotations
import os, json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SYSTEM = """你是金融內容分類助理。判斷一個 YouTube 財經頻道屬於哪一型：

- "call"（喊單型）：主要在「點名個股或產業、叫你買/看好某些標的」。重點是選股，
  通常不講明確到期日。例：解盤喊進台積電、看好半導體、報明牌。
- "forecast"（預言型）：主要在「預測某資產或大盤未來的漲跌方向」，常帶時間框架
  （某月、某週、下半年）。重點是擇時/方向判斷，不是選個股。例：預測美股下個月崩、
  比特幣本週漲、用命理/總經推估大盤方向。

只根據內容主軸判斷。輸出 JSON：
{"type":"call"或"forecast","confidence":"high"或"medium"或"low","reason":"一句理由（引用標題特徵）"}
只輸出 JSON。"""


def classify(titles: list[str], sample_text: str = "") -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"type": None, "confidence": "low", "reason": "缺 DEEPSEEK_API_KEY"}
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    sample_titles = "\n".join(f"- {t}" for t in titles[:15])
    user = f"頻道標題樣本：\n{sample_titles}\n"
    if sample_text:
        user += f"\n一份逐字稿開頭樣本：\n{sample_text[:800]}\n"
    user += "\n請判型。"
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            temperature=0.0, max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        r = json.loads(raw)
        if r.get("type") not in ("call", "forecast"):
            r["type"] = None
        return r
    except Exception as e:
        return {"type": None, "confidence": "low", "reason": f"LLM錯誤:{e}"}


# 自測：對現有 4 類用快取標題回測，須各自判對
def _self_test():
    import sqlite3, config
    cases = []
    # DAC
    try:
        d = json.load(open("data_cache/dac_transcripts.json", encoding="utf-8"))
        cases.append(("鄭博見 DAC", "forecast", [v["title"] for v in d[:15]]))
    except FileNotFoundError:
        pass
    # 吳昌華
    try:
        d = json.load(open("data_cache/wu_transcripts.json", encoding="utf-8"))
        cases.append(("吳昌華", "forecast", [v["title"] for v in d[:15]]))
    except FileNotFoundError:
        pass
    # KOL（從 DB 取一個頻道的標題）
    try:
        conn = sqlite3.connect(config.STOCK_DB_PATH)
        cid = config.TARGET_CHANNELS[0]["channel_id"]
        nm = config.TARGET_CHANNELS[0]["name"]
        ts = [r[0] for r in conn.execute(
            "SELECT title FROM video_log WHERE channel_id=? AND title!='' LIMIT 15", [cid]).fetchall()]
        conn.close()
        if ts:
            cases.append((nm + "(KOL)", "call", ts))
    except Exception as e:
        print("KOL 取標題失敗:", e)

    ok = 0
    for name, expect, titles in cases:
        r = classify(titles)
        hit = "✓" if r.get("type") == expect else "✗"
        if r.get("type") == expect:
            ok += 1
        print(f"  {hit} {name:<16} 期望={expect:<8} 判得={r.get('type')} ({r.get('confidence')}) — {r.get('reason','')[:40]}")
    print(f"\n判型正確 {ok}/{len(cases)}")


if __name__ == "__main__":
    _self_test()
