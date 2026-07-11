"""
ask_combined.py — 合併問答 agent。
把四個工具掛進同一個 DeepSeek agent loop：
  list_analysts / list_targets / query_calls（階段一：命中/報酬，引擎算）
  + search_transcript（階段二：撈他原話，向量 RAG）
使用者問一句「他X月喊Y那次準嗎」→ AI 自己先撈原話、再查命中、合起來答。
"""
import json
import sys
from openai import OpenAI

import config
import ask_query
import ask_transcript
import scorecard

client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

TOOLS = [
    {"type": "function", "function": {
        "name": "list_analysts",
        "description": "列出所有可查的分析師姓名與類型。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "list_targets",
        "description": "列出某分析師實際喊過的標的（依次數排序）。推薦標的前先叫這個。",
        "parameters": {"type": "object", "properties": {
            "analyst": {"type": "string"}}, "required": ["analyst"]},
    }},
    {"type": "function", "function": {
        "name": "query_calls",
        "description": "查某分析師對某標的的實際喊單與『命中/賺賠/超額報酬』。數字皆為引擎算，是判斷『準不準』的唯一依據。",
        "parameters": {"type": "object", "properties": {
            "analyst": {"type": "string"},
            "ticker": {"type": "string", "description": "標的關鍵字，如 SOXX/環球晶"},
            "direction": {"type": "string", "enum": ["bullish", "bearish"]},
            "start": {"type": "string", "description": "起日 YYYY-MM-DD"},
            "end": {"type": "string", "description": "迄日 YYYY-MM-DD"},
            "hold": {"type": "integer", "enum": [5, 20, 60, 120, 250]},
            "group_by": {"type": "string", "enum": ["month", "quarter", "year"],
                         "description": "要逐月/季/年看勝率時填這個，引擎會回 groups 分組摘要。不要自己把 calls 明細分組計算。"},
        }, "required": ["analyst"]},
    }},
    {"type": "function", "function": {
        "name": "get_scorecard",
        "description": "查某分析師的『卡片彙總戰績』——就是網站個人卡三部分那些頭條數字，全部引擎預先算好：①$100 跟他終值 vs 買大盤終值、最大回撤、年化超額+p值+95%CI+FDR顯著+判決句 ②贏大盤率、做多/看空命中筆數、有賺沒 ③贏過亂猜(基準50%)、集中度、贏輸幅度、每筆期望、近況趨勢、神單/雷單。問「回撤多少/顯著嗎/集中度/贏過亂猜/終值」這類彙總題就用這個，不要自己從逐筆算。",
        "parameters": {"type": "object", "properties": {
            "analyst": {"type": "string"},
            "hold": {"type": "integer", "enum": [5, 20, 60, 120, 250],
                     "description": "持有天數，預設 20"}},
            "required": ["analyst"]},
    }},
    {"type": "function", "function": {
        "name": "list_transcript_analysts",
        "description": "列出目前有逐字稿可搜尋的分析師（slug + 中文名）。用 search_transcript 前先確認該分析師有沒有逐字稿。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "search_transcript",
        "description": "在指定分析師的逐字稿裡用語意搜尋撈出『他當時原話』。用來知道他『說了什麼/怎麼想』，但不能用來判斷準不準（那要用 query_calls）。先用 list_transcript_analysts 確認該分析師有逐字稿。",
        "parameters": {"type": "object", "properties": {
            "analyst_slug": {"type": "string", "description": "list_transcript_analysts 回傳的 slug，如 gooaye/dac/wu"},
            "question": {"type": "string", "description": "要找的主題，如 對半導體的看法"},
            "k": {"type": "integer", "description": "撈幾段，預設 5"},
        }, "required": ["analyst_slug", "question"]},
    }},
]

SYSTEM = """你是這個量化回測專案的問答助手。鐵律：
0. 「彙總/頭條數字」——終值($100 跟他 vs 買大盤)、最大回撤、年化超額、p值、信賴區間、FDR/Romano-Wolf 是否顯著、贏大盤率、贏過亂猜、集中度、贏輸幅度、每筆期望、近況趨勢、神單/雷單——一律用 get_scorecard 讀引擎算好的值，【絕不】自己從 query_calls 的逐筆明細去複利、算回撤、算顯著性。query_calls 只用來看「某段時間、某標的的逐筆賺賠與勝率」。
1. 判斷「準不準/命中/賺賠」一律以引擎數字(get_scorecard 或 query_calls)為準，【絕不】用逐字稿裡他自誇的話當證據。
2. search_transcript 只用來補「他當時怎麼說」的脈絡與原話引用，撈到的原話要標第幾集。查前先用 list_transcript_analysts 確認該分析師的 slug、有沒有逐字稿。
3. 遇到「他X月喊Y那次準嗎」這種題：先 search_transcript 找他原話，再 query_calls 查那段期間該標的的實際命中，最後合起來答（他說了什麼 + 結果如何）。
4. outcome=pending 代表未到期，不可講成賺賠；n_scored 很小要提醒樣本不足。
   ★ 要講「逐月/逐季勝率」時，一律用 group_by 參數讓引擎算好的 groups，【絕不】自己把 calls 明細分組數勝負。calls 明細只拿來『舉例、講哪筆做得好/哪筆踩雷』，不拿來算統計。
5. 只有 list_transcript_analysts 回傳的分析師才有逐字稿可查，其他人查無資料就誠實說沒有，不要編。用繁體中文、口語但精確。"""


def run_tool(name, args):
    if name == "list_analysts":
        return ask_query.list_analysts()
    if name == "list_targets":
        return ask_query.list_targets(**args)
    if name == "query_calls":
        return ask_query.query_calls(**args)
    if name == "get_scorecard":
        return scorecard.get_scorecard(**args)
    if name == "list_transcript_analysts":
        return [{"slug": s, "name": ask_transcript.SLUG_NAME.get(s, s)}
                for s in ask_transcript.available_slugs()]
    if name == "search_transcript":
        slug = args["analyst_slug"]
        if slug not in ask_transcript.available_slugs():
            return {"error": f"{slug} 沒有逐字稿，先用 list_transcript_analysts 確認 slug"}
        hits = ask_transcript.search(args["question"], slug, args.get("k", 5))
        return [{"ep": h["ep"], "date": h["date"], "title": h["title"],
                 "text": h["text"], "score": round(h["score"], 3)} for h in hits]
    return {"error": f"unknown tool {name}"}


def ask(question, history=None, max_turns=6):
    """history: 之前的對話（[{role:'user'/'assistant', content:str}, …]），
    讓追問能接上文脈。只保留純文字往返，不含內部 tool 呼叫。"""
    msgs = [{"role": "system", "content": SYSTEM}]
    for h in (history or []):
        role = h.get("role"); content = h.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": question})
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
    q = " ".join(sys.argv[1:]) or "股癌 2023 年下半年喊半導體那陣子，他當時怎麼說？後來準不準？"
    print(ask(q))
