"""
ask_transcript.py — 階段二「翻原始逐字稿」向量 RAG（多分析師版）。

流程：切塊 → 算 embedding 存檔（每位分析師各一份索引）→ 查詢時找最近 k 段 → 交 LLM 照原文回答。
embedding 用本機免費模型（sentence-transformers），不花錢、不用 key。
安裝：pip install sentence-transformers

支援的分析師（slug 對應 data_cache/{slug}_transcripts.json）：
  gooaye = 股癌（謝孟恭）／dac = 鄭博見 DAC／wu = 吳昌華
新增一位只要 fetch_transcripts.py 抓出 data_cache/{slug}_transcripts.json 就自動可用。
"""
import glob
import json
import os
import pickle
import re
import numpy as np
from openai import OpenAI

import config

# ── 設定 ──────────────────────────────────────────────────────
EMB_MODEL = "BAAI/bge-small-zh-v1.5"   # 專門中文檢索的本機模型（比多語 MiniLM 強很多）
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："  # BGE 官方建議：查詢端加這句提示

# slug → 中文分析師名稱（給 LLM 看/答覆用；也是 list_transcript_analysts 的來源）
SLUG_NAME = {
    "gooaye": "股癌（謝孟恭）",
    "dac": "鄭博見 DAC",
    "wu": "吳昌華",
}


def _load_kol_names():
    """kol_* slug 的中文名不寫死在這裡，從 analysts.kol_registry() 動態補進 SLUG_NAME。"""
    try:
        import analysts as ana
        for name, cfg in ana.kol_registry().items():
            SLUG_NAME.setdefault(cfg["slug"], name)
    except Exception:
        pass


_load_kol_names()


def available_slugs() -> list[str]:
    """掃 data_cache/*_transcripts.json，回傳目前真的有逐字稿的 slug。"""
    out = []
    for path in glob.glob("data_cache/*_transcripts.json"):
        slug = re.sub(r"_transcripts\.json$", "", os.path.basename(path))
        out.append(slug)
    return sorted(out)


_model = None
def _get_model():
    """延遲載入 embedding 模型（第一次呼叫才載，之後所有分析師共用同一個模型）。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMB_MODEL)
    return _model


# ── 步驟 1：切塊 ───────────────────────────────────────────────
def chunk(text, size=500, overlap=50):
    """把一大段文字切成每 size 字一塊，前後重疊 overlap 字（避免切斷句子）。"""
    out = []
    for i in range(0, len(text), size - overlap):
        piece = text[i:i + size].strip()
        if piece:
            out.append(piece)
    return out


def _norm_meta(row: dict) -> dict | None:
    """不同人抓稿的欄位不一樣（股癌用 ep/date，其他用 video_id/upload_date），統一成 {ep,date,title,transcript}。"""
    text = row.get("transcript")
    if not text:
        return None
    return {
        "ep": row.get("ep", row.get("video_id", "")),
        "date": row.get("date", row.get("upload_date", "")),
        "title": row.get("title", ""),
        "transcript": text,
    }


def _index_path(slug: str) -> str:
    return f"data_cache/{slug}_rag_index.pkl"


def _transcripts_path(slug: str) -> str:
    return f"data_cache/{slug}_transcripts.json"


# ── 步驟 2：建索引（離線，每位分析師各一份）─────────────────────
def build_index(slug: str):
    """讀 data_cache/{slug}_transcripts.json → 切塊 → 算 embedding → 存 (metas, matrix)。"""
    raw = json.load(open(_transcripts_path(slug), encoding="utf-8"))
    metas = []
    for row in raw:
        m = _norm_meta(row)
        if m is None:
            continue
        for piece in chunk(m["transcript"]):
            metas.append({"ep": m["ep"], "date": m["date"], "title": m["title"], "text": piece})
    texts = [m["text"] for m in metas]
    print(f"[{slug}] 共 {len(texts)} 塊，開始算 embedding…")
    mat = _get_model().encode(texts, show_progress_bar=True,
                              normalize_embeddings=True)   # 一次算全部
    pickle.dump({"metas": metas, "mat": np.asarray(mat, dtype=np.float32)},
                open(_index_path(slug), "wb"))
    print(f"[{slug}] 完成 → {_index_path(slug)}")


def build_all_indexes(force: bool = False):
    """幫所有目前有逐字稿、但還沒建索引的分析師建索引。"""
    for slug in available_slugs():
        if force or not os.path.exists(_index_path(slug)):
            build_index(slug)


# ── 步驟 3：查詢時找最近 k 段（每位分析師各自的索引，用 dict 快取）───
_indexes: dict[str, dict] = {}
def _load_index(slug: str):
    if slug not in _indexes:
        path = _index_path(slug)
        if not os.path.exists(path):
            build_index(slug)
        _indexes[slug] = pickle.load(open(path, "rb"))
    return _indexes[slug]


def search(question, slug="gooaye", k=5):
    """把問題 embed → 跟指定分析師的所有塊算相似度 → 回最像的前 k 塊。"""
    idx = _load_index(slug)
    q = _get_model().encode([QUERY_PREFIX + question], normalize_embeddings=True)[0]
    sims = idx["mat"] @ q                          # 已正規化 → 內積即 cosine
    top = np.argsort(sims)[::-1][:k]
    return [{**idx["metas"][i], "score": float(sims[i])} for i in top]


# ── 步驟 4：交 LLM 照原文回答（強制引用）──────────────────────
client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

def ask_transcript(question, slug="gooaye", k=5):
    name = SLUG_NAME.get(slug, slug)
    hits = search(question, slug, k)
    context = "\n\n".join(
        f"[第{h['ep']}集 {h['date']}]（{h['title']}）\n{h['text']}" for h in hits)
    prompt = f"""你是{name}逐字稿的問答助手。只根據下面的逐字稿片段回答，
每個論點都要標明來自第幾集。片段裡沒講到的，就說「逐字稿沒提到」，
絕對不要用你自己的知識補充或推測。用繁體中文。

【逐字稿片段】
{context}

【問題】{question}"""
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0)
    return resp.choices[0].message.content


if __name__ == "__main__":
    import sys
    slugs = available_slugs()
    print("可查逐字稿的分析師：", {s: SLUG_NAME.get(s, s) for s in slugs})
    slug = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in slugs else "gooaye"
    q = " ".join(sys.argv[2:]) or "對疫情的看法是什麼？"
    if not os.path.exists(_index_path(slug)):
        print(f"[{slug}] 索引不存在，先建索引…")
        build_index(slug)
    print(f"\nＱ({SLUG_NAME.get(slug, slug)}): {q}\n")
    print(ask_transcript(q, slug))
