"""LLM 情緒評分模組：DeepSeek API + 行為金融反應過度/不足框架。

對應 PLAN.md 第 2.1 節「LLM 實戰語意特徵工程」。

核心設計：
- 三維評分（bullish / retail_mobilization / emotion_intensity），各 0-5 分。
- 反諷 & 反向情緒辨識：Prompt 明確要求 LLM 結合上下文判斷老師真實意圖。
- JSON 強制輸出 + 解析失敗重試（最多 LLM_RETRY 次）。
- 字幕過長時分段摘要再合併（避免超出 context window）。
- 回傳值同時包含「關注度代理」（字幕中提到該板塊的句子數），
  供行為框架判斷「反應不足（低關注）vs 反應過度（高關注）」。
"""

from __future__ import annotations

import json
import re
import time
import warnings
from typing import Optional

from openai import OpenAI

import config


_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未設定，請在 .env 填入。")
        _client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _client


# --------------------------------------------------------------------------
# Prompt 設計
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一位專業的台灣股票市場行為金融分析師。
你的任務是閱讀台灣股票投顧老師的 YouTube 影片字幕，
針對指定的「科技板塊」，評估老師對該板塊的真實態度。

【重要：反諷與反向情緒辨識規則】
- 老師有時使用反諷語氣，例如：「這種爛股票你還敢買？」（實際意圖是警告散戶不要買）
  或「大家快去追啊，反正錢多」（反諷看多，實際是警示）。
- 你必須結合上下文判斷老師的「真實意圖」，而非字面意思。
- 如果老師整段都在批評或警告某板塊，bullish 應該給低分（0-1），不要因為提到板塊名稱就給高分。
- 如果老師明確推薦、看好、喊進場，bullish 才給高分（4-5）。

【評分維度定義】
bullish（0-5）：老師對此板塊的真實看多程度。
  0 = 明確看空/警告  2.5 = 中性/沒提  5 = 非常強烈看多且推薦進場

retail_mobilization（0-5）：老師號召散戶買進的強度。
  0 = 完全沒呼籲  5 = 強烈呼籲大量散戶馬上進場

emotion_intensity（0-5）：老師談到此板塊時的情緒瘋狂程度（不論方向）。
  0 = 冷靜理性  5 = 極度亢奮或極度恐慌

mention_count：字幕中明確提到此板塊相關詞語的大約次數（整數）。
  用途：關注度代理——次數低=反應不足（動能訊號），次數高=反應過度（反轉訊號）。

【輸出格式】
只能輸出 JSON，不得有任何說明文字。格式：
{
  "bullish": <0-5的數字，可以是小數>,
  "retail_mobilization": <0-5的數字>,
  "emotion_intensity": <0-5的數字>,
  "mention_count": <整數>,
  "reasoning": "<一句話說明你的判斷依據（含反諷識別）>"
}
"""

USER_PROMPT_TEMPLATE = """以下是本週投顧影片字幕（合併後）：

---字幕開始---
{transcript_text}
---字幕結束---

請評估老師對【{sector}】板塊的態度，輸出 JSON。
如果字幕完全沒有提到此板塊或相關個股，mention_count=0，bullish=2.5，其餘填 0。
"""

# 板塊關鍵字（用來做粗篩，減少送給 LLM 的無關文字量）
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "先進封裝": ["先進封裝", "CoWoS", "SoIC", "日月光", "矽品", "封測"],
    "IC設計": ["IC設計", "聯發科", "聯詠", "瑞昱", "晶片設計", "Fabless"],
    "散熱": ["散熱", "奇鋐", "雙鴻", "建準", "液冷", "熱管", "均熱板"],
    "PCB": ["PCB", "欣興", "南電", "景碩", "電路板", "載板"],
    "組裝": ["組裝", "鴻海", "廣達", "緯創", "EMS", "代工廠", "伺服器組裝"],
    "記憶體": ["記憶體", "南亞科", "華邦電", "十銓", "DRAM", "HBM", "NAND"],
    "面板": ["面板", "群創", "友達", "彩晶", "LCD", "OLED", "Display"],
}

MAX_CHARS_PER_CALL = 8000   # 單次送給 LLM 的字幕字數上限


def _truncate_to_relevant(text: str, sector: str) -> str:
    """只保留包含板塊關鍵字的段落 ± 上下文，大幅減少 token 用量。"""
    keywords = SECTOR_KEYWORDS.get(sector, [sector])
    sentences = re.split(r"[。！？\n]", text)
    relevant, window = [], 2
    for i, s in enumerate(sentences):
        if any(k in s for k in keywords):
            lo, hi = max(0, i - window), min(len(sentences), i + window + 1)
            relevant.extend(sentences[lo:hi])
    if not relevant:
        # 沒有相關句子 → 仍送開頭摘要（讓 LLM 輸出 mention_count=0）
        return text[:MAX_CHARS_PER_CALL]
    joined = "。".join(dict.fromkeys(relevant))  # 去重保序
    return joined[:MAX_CHARS_PER_CALL]


def _call_llm(transcript_text: str, sector: str) -> dict:
    """呼叫 DeepSeek，回傳解析後的 dict；失敗則 raise。"""
    client = _get_client()
    text_for_prompt = _truncate_to_relevant(transcript_text, sector)
    user_msg = USER_PROMPT_TEMPLATE.format(
        transcript_text=text_for_prompt,
        sector=sector,
    )
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    # 去掉 markdown code fence（DeepSeek 有時會包 ```json ... ```）
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def score_sector(transcript_text: str, sector: str) -> dict:
    """對單一板塊評分，含重試。回傳 dict 或 None（重試全失敗）。

    回傳格式：
    {
        "bullish": float,           # 0-5
        "retail_mobilization": float,
        "emotion_intensity": float,
        "mention_count": int,
        "reasoning": str,
    }
    """
    last_err = None
    for attempt in range(config.LLM_RETRY):
        try:
            result = _call_llm(transcript_text, sector)
            # 基本欄位驗證
            for key in ("bullish", "retail_mobilization", "emotion_intensity", "mention_count"):
                if key not in result:
                    raise ValueError(f"LLM 輸出缺少欄位: {key}")
                if key != "mention_count":
                    v = float(result[key])
                    if not (0.0 <= v <= 5.0):
                        raise ValueError(f"{key}={v} 超出 0-5 範圍")
            return result
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            warnings.warn(f"[{sector}] LLM 評分失敗（attempt {attempt+1}）: {e}，{wait}s 後重試")
            time.sleep(wait)

    warnings.warn(
        f"[{sector}] LLM 評分全部重試失敗（{config.LLM_RETRY} 次）: {last_err}\n"
        "→ 此板塊情緒特徵標記為缺失（NaN），不可硬塞 0。"
    )
    return None   # 呼叫方須處理 None（PLAN.md：失敗不可硬塞 0）


# ==========================================================================
# ILRS 核心：逐頻道板塊「被點名」偵測（KOL 密度的原子操作）
# ==========================================================================
# 與 score_* 的差別：
#   score_*    → 對「合併所有頻道」評情緒分數（次數型），算不出 KOL 密度。
#   detect_*   → 對「單一頻道」一週字幕，一次回 7 板塊是否「被實質討論」布林。
#   KOL 密度 = 被點名的頻道數 / 當週有效頻道數（在 build_historical_sentiment 彙整）。
MENTION_SYSTEM_PROMPT = """你是台灣股市投顧影片的內容分類助手。
給你「某一位投顧老師、某一週」的影片字幕，判斷他這週是否「實質討論／推薦／點名」了以下 7 個科技板塊。

【判斷標準】
- 實質討論 = 老師有針對該板塊或其代表個股，給出看法、買賣建議、題材分析、目標價等（不論看多看空）。
- 只是「順口帶過一個股票名稱」、或「純粹回答觀眾無關提問」不算實質討論。
- 看空/警告也算「實質討論」（mention=true），因為老師確實把注意力放在這個板塊。
- 寧可嚴格：拿不準就給 false。

【7 大板塊與代表個股】
先進封裝：日月光、矽品、頎邦、南茂、CoWoS、SoIC、封測
IC設計：聯發科、聯詠、瑞昱、晶片設計、Fabless
散熱：奇鋐、雙鴻、建準、液冷、熱管、均熱板
PCB：欣興、南電、景碩、電路板、載板、ABF
組裝：鴻海、廣達、緯創、緯穎、EMS、伺服器組裝、代工
記憶體：南亞科、華邦電、十銓、威剛、群聯、DRAM、HBM、NAND、記憶體
面板：群創、友達、彩晶、LCD、OLED、Display

【輸出格式】
只能輸出 JSON，不得有任何其他文字。每個板塊一個布林值：
{
  "先進封裝": true/false,
  "IC設計": true/false,
  "散熱": true/false,
  "PCB": true/false,
  "組裝": true/false,
  "記憶體": true/false,
  "面板": true/false
}
"""

MENTION_USER_TEMPLATE = """以下是【{channel}】這週的影片字幕（可能含多部影片）：

---字幕開始---
{transcript_text}
---字幕結束---

請判斷這位老師本週是否實質討論了 7 大板塊，輸出 JSON。"""

MENTION_MAX_CHARS = 30000   # 單頻道單週字幕上限（DeepSeek 長 context，但仍設防爆 token）


def detect_sector_mentions(channel: str, transcript_text: str) -> Optional[dict[str, bool]]:
    """對單一頻道一週的合併字幕，一次 LLM 呼叫回傳 7 板塊是否被實質討論。

    回傳 {sector: bool}；全部重試失敗回 None（呼叫方須視為該頻道當週無效，不可硬塞 False）。
    """
    if not transcript_text or not transcript_text.strip():
        return None
    text = transcript_text[:MENTION_MAX_CHARS]
    client = _get_client()
    user_msg = MENTION_USER_TEMPLATE.format(channel=channel, transcript_text=text)

    last_err = None
    for attempt in range(config.LLM_RETRY):
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=512,
                messages=[
                    {"role": "system", "content": MENTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
            # 正規化：缺漏的板塊補 False，多餘的鍵忽略
            return {sec: bool(parsed.get(sec, False)) for sec in config.SECTOR_NAMES}
        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            warnings.warn(f"[{channel}] mention 偵測失敗（attempt {attempt+1}）: {e}，{wait}s 後重試")
            time.sleep(wait)
    warnings.warn(f"[{channel}] mention 偵測全部重試失敗: {last_err} → 該頻道當週標記為無效（None）")
    return None


def score_all_sectors(weekly_transcripts: list[dict]) -> dict[str, dict | None]:
    """對一週所有頻道字幕合併後，評估 7 大板塊。

    weekly_transcripts: fetch_all_channels() 的輸出。
    回傳: {sector_name: score_dict or None}
    """
    if not weekly_transcripts:
        warnings.warn("本週無任何字幕資料，所有板塊情緒返回 None。")
        return {sec: None for sec in config.SECTOR_NAMES}

    # 合併所有頻道、所有影片的字幕（依發布時間排序）
    sorted_items = sorted(weekly_transcripts, key=lambda x: x.get("published_at", ""))
    combined = "\n\n".join(
        f"[{it['channel']} / {it['title']}]\n{it['transcript']}"
        for it in sorted_items
    )
    print(f"  合併字幕總長: {len(combined):,} 字元，開始 LLM 評分...")

    scores = {}
    for sector in config.SECTOR_NAMES:
        scores[sector] = score_sector(combined, sector)
        print(f"    {sector}: {scores[sector]}")


# ==========================================================================
# 個股版：對單部影片逐字稿，評估所有被提到個股的三維情緒
# ==========================================================================

STOCK_SCORE_SYSTEM_PROMPT = """你是一位台灣股票市場行為金融分析師。
你的任務是閱讀台灣投顧老師的 YouTube 影片逐字稿，
找出所有「被實質討論」的個股，並對每支個股給出三維情緒評分。

【判斷標準】
- 實質討論 = 老師針對該個股給出看法、買賣建議、題材分析、目標價等（不論看多看空）。
- 只是順口帶過、純念股票名稱不算。
- 反諷語氣要辨識真實意圖（叫賣的反諷 bullish 低分，叫買的反諷 bullish 高分）。

【評分維度】
bullish（0-5）：對此個股的真實看多程度。0=明確看空, 2.5=中性, 5=強力推薦買進
retail_mobilization（0-5）：號召散戶買進的強度。0=沒呼籲, 5=強烈叫散戶馬上衝
emotion_intensity（0-5）：談到此個股時的情緒亢奮/恐慌程度。0=冷靜, 5=極度激動
mention_count（整數）：影片中提到此個股相關詞語的次數

【輸出格式】
只能輸出 JSON，格式如下，key 為股票代碼（數字字串）：
{
  "2317": {"bullish": 3.5, "retail_mobilization": 2.0, "emotion_intensity": 3.0, "mention_count": 4},
  "2382": {"bullish": 4.0, "retail_mobilization": 3.5, "emotion_intensity": 4.0, "mention_count": 6}
}
如果沒有任何個股被實質討論，輸出空物件：{}
"""

STOCK_SCORE_USER_TEMPLATE = """以下是投顧影片逐字稿：

---逐字稿開始---
{transcript}
---逐字稿結束---

【已知個股關鍵字對照表】
{stock_keywords}

請找出所有被實質討論的個股（用股票代碼作 key），輸出 JSON 評分。
只輸出有實質討論的個股，沒提到或只是帶過的不要列入。"""


def score_stocks_in_transcript(transcript: str, stock_keywords: dict[str, list[str]]) -> dict:
    """對單部影片逐字稿，評估所有被提到個股的三維情緒。

    stock_keywords: {stock_code: [關鍵字列表]}，如 config.STOCK_KEYWORDS
    回傳: {stock_code: {bullish, retail_mobilization, emotion_intensity, mention_count}}
    失敗回傳空 dict（不可硬塞 0）。
    """
    if not transcript or len(transcript.strip()) < 50:
        return {}

    # 建立關鍵字對照表字串給 LLM 參考
    kw_lines = "\n".join(
        f'{code}: {", ".join(kws)}' for code, kws in stock_keywords.items()
    )

    client = _get_client()
    user_msg = STOCK_SCORE_USER_TEMPLATE.format(
        transcript=transcript[:12000],  # 控制 token 用量
        stock_keywords=kw_lines,
    )

    last_err = None
    for attempt in range(config.LLM_RETRY):
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": STOCK_SCORE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            raw = re.sub(r",\s*([}\]])", r"\1", raw)  # 修復尾逗號
            parsed = json.loads(raw)

            # 驗證格式
            result = {}
            for code, scores in parsed.items():
                if code not in stock_keywords:
                    continue  # 只保留已知個股
                result[code] = {
                    "bullish": max(0.0, min(5.0, float(scores.get("bullish", 2.5)))),
                    "retail_mobilization": max(0.0, min(5.0, float(scores.get("retail_mobilization", 0)))),
                    "emotion_intensity": max(0.0, min(5.0, float(scores.get("emotion_intensity", 0)))),
                    "mention_count": max(0, int(scores.get("mention_count", 0))),
                }
            return result

        except Exception as e:
            last_err = e
            wait = 2 ** attempt
            warnings.warn(f"[stock_score] LLM 評分失敗（attempt {attempt+1}）: {e}，{wait}s 後重試")
            time.sleep(wait)

    warnings.warn(f"[stock_score] 全部重試失敗: {last_err} → 回傳空 dict")
    return {}
    return scores
