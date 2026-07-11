"""Render the Chinese site, inject English UI translations, screenshot each section
into docs/assets/en/. The live site is NOT modified — this is a throwaway render."""
from playwright.sync_api import sync_playwright
import pathlib

ROOT = pathlib.Path("/Users/henrylin/Desktop/trading model")
OUT = pathlib.Path("/Users/henrylin/Desktop/kol-track-record-src/docs/assets/en")
OUT.mkdir(parents=True, exist_ok=True)
url = "file://" + str((ROOT / "index.html").resolve())

# Ordered longest-first phrase map (applied as substring replace on text nodes).
PAIRS = [
    ("14 位財經網紅、18,160 句喊盤，每一句都用真實股價算帳。經嚴格統計校正後，沒有一位能證明打敗大盤。下方 $222 雖略高於 $215，但這點差距在統計上與丟銅板無異。",
     "14 finance influencers, 18,160 calls — every one scored against real prices. After rigorous statistical correction, not one can be shown to beat the market. The $222 below edges out $215, but that gap is statistically indistinguishable from a coin flip."),
    ("11 位「未校正顯著」、多重比較校正後存活 0 位——同時檢定 14 個人，總會有人單憑運氣看起來顯著。點任一列看完整分析 →",
     "11 look “raw-significant”; 0 survive after multiple-testing correction — test 14 people at once and someone always looks significant by luck. Click any row for the full analysis →"),
    ("資料 2020–2026：18,160 次喊盤 + 751 次產業表態 + 20 條預言",
     "Data 2020–2026: 18,160 calls + 751 sector views + 20 predictions"),
    ("中位方向命中 56%（50% ＝ 丟銅板）", "Median directional hit 56% (50% = coin flip)"),
    ("喊買前平均已漲 +8.2%", "Avg +8.2% run-up before the call"),
    ("卡內數字＝完整追蹤期（可切持有天數）；排行榜為近12個月，兩者口徑不同、不會相等。",
     "Card figures = full tracking period (hold days adjustable); leaderboard = last 12 months — different windows, not comparable."),
    ("做多原始檢定顯著，但多重比較校正（Romano-Wolf）後消失；但他的看空大多看錯",
     "Long calls test significant raw, but vanish after multiple-testing correction (Romano–Wolf); his short calls are mostly wrong"),
    ("上方 % 以『週』為單位（每週一批、贏大盤的週佔比）；下方長條以『逐筆喊盤』為單位（每筆贏／輸大盤的筆數），兩者單位不同，數字不會一樣。",
     "The % above is weekly (share of weeks that beat the index, one batch per week); the bars below are per-call (count of individual calls that beat/lost to the index). Different units — the numbers won't match."),
    ("（$100 跟他 vs $100 買綜合大盤，全期）", "($100 following them vs $100 buying the blended index, full period)"),
    ("持有期間年化超額 +2.0%（p=0.341）", "Annualized excess over hold +2.0% (p=0.341)"),
    ("持倉紀錄（全部 743 筆，這就是 $ 怎麼來的）", "Position log (all 743 calls — this is where the $ comes from)"),
    ("命中紀錄（全部 743 筆，自己對）", "Hit log (all 743 calls, vs self)"),
    ("第三部分 · 這是本事，還是運氣？", "Part 3 · Skill, or luck?"),
    ("第一部分 · 策略表現", "Part 1 · Strategy performance"),
    ("第二部分 · 方向預測準度", "Part 2 · Directional accuracy"),
    ("前20%喊單佔了88%正超額", "Top 20% of calls drive 88% of positive excess"),
    ("命中率×贏幅 +（1−命中率）×輸幅", "hit×win + (1−hit)×loss"),
    ("等權每筆平均超額，非組合 $ 結果", "Equal-weighted avg excess per call, not portfolio $"),
    ("與丟銅板相當（丟銅板＝50%）", "On par with a coin flip (coin flip = 50%)"),
    ("平均贏多少 vs 平均輸多少", "Avg win vs avg loss"),
    ("5段命中率走勢（近期在右）", "Hit rate across 5 segments (recent on right)"),
    ("策略最大回撤 -52%", "Strategy max drawdown -52%"),
    ("策略最大回撤", "Strategy max drawdown"),
    ("做多準度（比大盤）", "Long accuracy (vs index)"),
    ("贏大盤率（週為單位）", "Beat-index rate (weekly)"),
    ("投顧戰績，逐筆驗算", "Analyst Track Records, Verified Call by Call"),
    ("投顧戰績實驗室", "KOL Track Record Lab"),
    ("$100 買綜合大盤", "$100 buying the blended index"),
    ("中位數（20 日持有）", "Median (20-day hold)"),
    ("$100 跟著做", "$100 following them"),
    ("$100 買大盤", "$100 buying the index"),
    ("$100 跟他", "$100 following them"),
    ("怎麼看這張圖", "How to read this chart"),
    ("自己選人比一比", "Compare analysts yourself"),
    ("＋ 加入分析師", "+ Add analyst"),
    ("神單 / 雷單", "Best / worst calls"),
    ("方向命中率", "Directional hit rate"),
    ("全期年化超額", "Annualized excess"),
    ("近12個月超額", "Last-12mo excess"),
    ("近12月超額", "12mo excess"),
    ("未校正顯著", "Raw-significant"),
    ("跟他實賺", "Actual return"),
    ("成長曲線", "Growth curve"),
    ("喊買時機", "Entry timing"),
    ("還原預設", "Reset"),
    ("全部分析師", "All analysts"),
    ("每筆期望", "Per-call expectancy"),
    ("贏/輸幅度", "Win/loss size"),
    ("近況趨勢", "Recent trend"),
    ("持有天數", "Hold days"),
    ("贏大盤", "Beat index"),
    ("輸大盤", "Lost to index"),
    ("比大盤", "vs index"),
    ("有賺沒", "Made $?"),
    ("集中度", "Concentration"),
    ("無顯著", "Not significant"),
    ("排序依", "Sort by"),
    ("分析師", "Analyst"),
    ("待定", "Pending"),
    ("基準", "Benchmark"),
    ("方向", "Direction"),
    ("做多", "Long"),
    ("看空", "Short"),
    ("雙向", "Both"),
    ("實賺", "Actual return"),
    ("統計", "Stats"),
    ("清空", "Clear"),
    ("美股", "US"),
    ("台股", "TW"),
    ("追蹤", "Tracked"),
    ("大盤", "Index"),
]

# Long paragraphs that inline elements ($ numbers, icons) split into fragments —
# must be replaced at ELEMENT level (marker substring -> full English).
PARA = [
    ("每一句都用真實股價算帳",
     "14 finance influencers, 18,160 calls — every one scored against real prices. After rigorous statistical correction, not one can be shown to beat the market. The $222 below edges out $215, but that gap is statistically indistinguishable from a coin flip."),
    ("同時檢定 14 個人",
     "11 look “raw-significant”; 0 survive after multiple-testing correction — test 14 people at once and someone always looks significant by luck. Click any row for the full analysis →"),
    ("兩者口徑不同",
     "Card figures = full tracking period (hold days adjustable); leaderboard = last 12 months — different windows, not comparable."),
]

# JS: element-level paragraph swap + substring replace (longest-first) + regex.
INJECT = """
(args) => {
  const {pairs, para} = args;
  const rx = [
    [/(\\d[\\d,]*)\\s*次喊盤/g, '$1 calls'],
    [/(\\d[\\d,]*)\\s*句喊盤/g, '$1 calls'],
    [/(\\d[\\d,]*)\\s*次產業表態/g, '$1 sector views'],
    [/(\\d[\\d,]*)\\s*條預言/g, '$1 predictions'],
    [/(\\d[\\d,]*)\\s*筆/g, '$1 calls'],
    [/共\\s*(\\d+)\\s*個月/g, '$1 months'],
    [/(\\d+)\\s*日/g, '$1d'],
  ];
  const walk = (root) => {
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = []; let n; while (n = it.nextNode()) nodes.push(n);
    for (const t of nodes) {
      let v = t.nodeValue; if (!v || !v.trim()) continue;
      for (const [zh, en] of pairs) if (v.includes(zh)) v = v.split(zh).join(en);
      for (const [re, en] of rx) v = v.replace(re, en);
      t.nodeValue = v;
    }
  };
  const paraPass = () => {
    for (const [marker, en] of para) {
      let best = null, bestLen = Infinity;
      for (const el of document.querySelectorAll('body *')) {
        const tc = el.textContent || '';
        if (tc.includes(marker) && tc.length < bestLen) { best = el; bestLen = tc.length; }
      }
      if (best) best.textContent = en;
    }
  };
  window.__tr = () => { paraPass(); walk(document.body); };
  window.__tr();
}
"""

SHOTS = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width":1280,"height":1000}, device_scale_factor=2)
    pg.goto(url); pg.wait_for_timeout(1200)
    pg.evaluate(INJECT, {"pairs": PAIRS, "para": PARA})
    pg.wait_for_timeout(300)

    # 1. HERO — clip page from top down to where the leaderboard table starts
    tbl_top = pg.eval_on_selector("#ov-tbl", "e=>e.getBoundingClientRect().top + window.scrollY")
    pg.screenshot(path=str(OUT/"1_hero.png"), clip={"x":0,"y":0,"width":1280,"height":int(tbl_top)})
    SHOTS.append("1_hero.png")

    # 2. LEADERBOARD table element
    pg.query_selector("#ov-tbl").screenshot(path=str(OUT/"2_leaderboard.png"))
    SHOTS.append("2_leaderboard.png")

    # 3. COMPARE chart section
    pg.query_selector("#why").scroll_into_view_if_needed(); pg.wait_for_timeout(200)
    pg.evaluate("window.__tr()")
    pg.query_selector("#why").screenshot(path=str(OUT/"3_compare.png"))
    SHOTS.append("3_compare.png")

    # 4. CARD modal (Gooaye) — open, re-translate, screenshot the modal element
    pg.evaluate("openCard('股癌謝孟恭','股癌謝孟恭')"); pg.wait_for_timeout(700)
    pg.evaluate("window.__tr()"); pg.wait_for_timeout(200)
    pg.query_selector("#modal-股癌謝孟恭").screenshot(path=str(OUT/"4_card.png"))
    SHOTS.append("4_card.png")

    b.close()

print("SAVED:", SHOTS)
for s in SHOTS:
    f = OUT/s
    print(s, f.stat().st_size//1024, "KB")
