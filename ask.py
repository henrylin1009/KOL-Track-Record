"""
ask.py — 階段一「查決策事實」的上層問答（DeepSeek tool-calling）。

方法：Tool-Augmented LLM（不是向量 RAG）。
  LLM 只做兩件事：①把人話翻成 query_calls 的參數 ②把回傳數字講成人話。
  所有數字來自 ask_query.py（引擎算），LLM 一律不自行計算 / 不記憶數字。

用法：
  export DEEPSEEK_API_KEY=...
  python ask.py "郭哲榮喊環球晶賺了嗎？"
"""
import json
import sys
from openai import OpenAI

import config
import ask_query

client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

TOOLS = [
    {"type": "function", "function": {
        "name": "list_analysts",
        "description": "列出所有可查的分析師姓名與類型。回答前若不確定姓名先叫這個。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_targets",
        "description": "列出某分析師『實際喊過』的標的（依次數排序）。要推薦或確認某標的存不存在時先叫這個，避免建議查不到的代碼。",
        "parameters": {"type": "object", "properties": {
            "analyst": {"type": "string", "description": "分析師姓名"},
        }, "required": ["analyst"]},
    }},
    {"type": "function", "function": {
        "name": "query_calls",
        "description": "查某分析師對某標的的實際喊單與績效（策略報酬、大盤報酬、超額、勝率）。數字皆為回測引擎算出。",
        "parameters": {"type": "object", "properties": {
            "analyst": {"type": "string", "description": "分析師姓名，須為 list_analysts 內的精確名稱"},
            "ticker": {"type": "string", "description": "標的關鍵字，如 環球晶 / 台積 / SPY；不填=全部"},
            "direction": {"type": "string", "enum": ["bullish", "bearish"], "description": "看多/看空，不填=不限"},
            "start": {"type": "string", "description": "起日 YYYY-MM-DD"},
            "end": {"type": "string", "description": "迄日 YYYY-MM-DD"},
            "hold": {"type": "integer", "enum": [5, 20, 60, 120, 250], "description": "持有天數，預設 20"},
        }, "required": ["analyst"]},
    }},
]

SYSTEM = """你是這個量化回測專案的問答助手。鐵律：
1. 你【不做任何計算、不記憶任何數字】。所有績效數字一律呼叫 query_calls 取得，並如實引用。
2. 工具回傳裡 outcome=pending 代表「未到期、尚無結論」，no_price 代表「查無價格」——這些絕不可講成賺或賠，要明說「尚無結論」。
3. 若 n_scored 很小（如 1、2 筆），必須主動提醒「樣本太少，不足以下定論」。
4. 引用每筆時附上 quote（他原話）與日期，讓使用者能自己核對。
5. 查無資料就說沒有，不要編。用繁體中文、口語但精確。
6. 要「推薦使用者可以查哪些標的」前，先呼叫 list_targets 確認，只列真的喊過的標的，不要憑印象建議代碼（如 NVDA/AMD 可能其實不在資料裡）。"""


def run_tool(name, args):
    if name == "list_analysts":
        return ask_query.list_analysts()
    if name == "list_targets":
        return ask_query.list_targets(**args)
    if name == "query_calls":
        return ask_query.query_calls(**args)
    return {"error": f"unknown tool {name}"}


def ask(question: str, max_turns: int = 5) -> str:
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": question}]
    for _ in range(max_turns):
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL, messages=msgs,
            tools=TOOLS, temperature=0.0)
        m = resp.choices[0].message
        msgs.append(m)
        if not m.tool_calls:
            return m.content
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = run_tool(tc.function.name, args)
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(result, ensure_ascii=False)})
    return "（超過最大回合數，未能收斂）"


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "郭哲榮喊環球晶到底賺不賺？"
    print(ask(q))
