"""Render sql.html, inject English UI translations, screenshot to docs/assets/en/5_sql.png.
Throwaway render — the live page (Chinese) is not modified. Mirrors make_en_screenshots.py."""
from playwright.sync_api import sync_playwright
import pathlib

ROOT = pathlib.Path("/Users/henrylin/Desktop/trading model")
OUT = pathlib.Path("/Users/henrylin/Desktop/kol-track-record-src/docs/assets/en")
OUT.mkdir(parents=True, exist_ok=True)
url = "file://" + str((ROOT / "sql.html").resolve())

# Longest-first substring map (applied to text nodes).
PAIRS = [
    ("資料以 Parquet 存於", "Data stored as Parquet in"),
    ("以 SQL 查詢。", "with SQL."),
    ("唯讀護欄：僅允許 SELECT、自動 LIMIT、限流。",
     "Read-only guardrails: SELECT-only, auto-LIMIT, rate limiting."),
    ("用標準 SQL 直接查詢 94,177 筆分析師逐筆回測資料。",
     "Query all 94,177 per-call backtest rows directly with standard SQL."),
    ("各分析師 20 日勝率排行", "Win rate by analyst (20-day)"),
    ("不同持有天期的勝率", "Win rate by holding period"),
    ("看多 vs 看空誰準", "Long vs short accuracy"),
    ("被喊最多次的標的 Top 15", "Most-called tickers (Top 15)"),
    ("欄位：analyst 分析師／date 喊盤日／ticker 標的／direction 看多空／"
     "hold_days 持有天期／strat_ret 跟他報酬%／bench_ret 大盤%／excess_ret 超額%／"
     "hit 命中(hit/miss/pending)／is_pending 是否未到期",
     "Columns: analyst / date (call date) / ticker / direction / hold_days / "
     "strat_ret (return following them %) / bench_ret (index %) / excess_ret (excess %) / "
     "hit (hit/miss/pending) / is_pending"),
    ("SQL 遊樂場", "SQL Playground"),
    ("投顧戰績實驗室", "KOL Track Record Lab"),
    ("試試這些", "Try these"),
    ("自己來", "Your turn"),
    ("執行查詢", "Run query"),
    ("回總覽", "Back to overview"),
    ("，經", ", queried via"),
]

INJECT = """
(pairs) => {
  const it = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = []; let n; while (n = it.nextNode()) nodes.push(n);
  for (const t of nodes) {
    let v = t.nodeValue; if (!v || !v.trim()) continue;
    for (const [zh, en] of pairs) if (v.includes(zh)) v = v.split(zh).join(en);
    t.nodeValue = v;
  }
}
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 980}, device_scale_factor=2)
    pg.goto(url); pg.wait_for_timeout(600)
    pg.evaluate(INJECT, PAIRS)
    # note paragraph spans line breaks → replace at element level for reliability
    pg.eval_on_selector(".note", "e => e.textContent = "
        "'Columns:  analyst  ·  date (call date)  ·  ticker  ·  direction  ·  "
        "hold_days  ·  strat_ret (return following them %)  ·  bench_ret (index %)  ·  "
        "excess_ret (excess %)  ·  hit (hit/miss/pending)  ·  is_pending'")
    pg.wait_for_timeout(200)
    # clip from top through the "Run query" button
    btm = pg.eval_on_selector("#run", "e=>e.getBoundingClientRect().bottom + window.scrollY")
    pg.screenshot(path=str(OUT / "5_sql.png"),
                  clip={"x": 0, "y": 0, "width": 1280, "height": int(btm) + 24})
    b.close()

f = OUT / "5_sql.png"
print("SAVED", f, f.stat().st_size // 1024, "KB")
