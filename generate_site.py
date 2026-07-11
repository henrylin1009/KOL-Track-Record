"""生成自包含一頁式網站 index.html — v2 統一設計。

設計原則：
- 統一框架：每位分析師同一句 headline「$100 跟他 vs $100 買大盤」
- 類型（喊單/總經/命理）只是標籤＋篩選，不是不同章節
- 像網站不像報告：sticky nav、hero 單一問題、卡片牆、tab 圖表、細節摺疊
"""
import json, os
from verdict_rules import verdict as gen_verdict

def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None

# ── 第三部分：體檢表計算 ─────────────────────────────────
from scorecard import compute_health as _compute_health  # 單一真相源（AI 問答共用）

# ── 資料 ──────────────────────────────────────────────
# ── 單一真相源：全站數字皆由 calendar_multi.json 即時算 ───────────
# （2026-07-02 收斂：拔掉所有派系專屬凍結 JSON——kol_calendar/scorecard/
#  chart_meta/overall_stats/calendar_portfolio/dac_results/dac_equity/
#  gooaye_* 全退場。卡片、總覽、hero 一律讀 cm，加人自動涵蓋、不會對不上。）
cm = load("calendar_multi.json") or {}
cm_an = cm.get("analysts", {})
cm_meta = cm.get("meta", {})

# 每位 KOL 真實喊盤筆數 ← cm 的缺價稽核（coverage.n_calls＝實際納入筆數）
_kol_ncalls = {nm: (a.get("coverage") or {}).get("n_calls")
               for nm, a in cm_an.items()}

# 方法學常數（非逐次資料，內聯保留原顯示值）
BENCH_ANN = 47.1        # 買進持有基準年化 %
MDE_ANN = 17.7          # 最小可偵測效果 %/年（「未顯著」＝偵測不到）
LIMITUP_FRAC = 5.4      # 喊盤進場日漲停買不到比例 %

# ── 類型樣式（純白畫廊風：全部黑灰，只有漲跌紅綠）──
TYPE = {
    "call":  dict(label="個股選股"),
    "macro": dict(label="產業主題"),
    "myst":  dict(label="大盤擇時"),
}
LINE = "#16161f"   # 跟他的淨值線
MKTL = "#d2d6dc"   # 大盤線

_sidebar_items = []  # 第二頁 sidebar 用，card() 會 append

# ── 共用 sparkline ────────────────────────────────────
def spark(curve, mcurve, color=LINE, w=260, h=64, pad=4):
    allv = list(curve) + list(mcurve)
    lo, hi = min(allv), max(allv)
    rng = (hi - lo) or 1
    def pts(arr):
        n = len(arr)
        return " ".join(f"{pad+(w-2*pad)*i/(n-1):.1f},{h-pad-(h-2*pad)*(v-lo)/rng:.1f}"
                        for i, v in enumerate(arr))
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="spark">'
            f'<polyline points="{pts(mcurve)}" fill="none" stroke="{MKTL}" stroke-width="1.5"/>'
            f'<polyline points="{pts(curve)}" fill="none" stroke="{color}" stroke-width="1.8"/></svg>')

# ── Layer 3 統計格（三格：命中率/贏大盤率/最大回撤）────────
def make_stats3(uid, cm_key, is_market_bet=False, dac_dir=None):
    """回傳第3層預測準度 HTML。uid用於JS動態更新；DAC用dac_dir覆蓋。"""
    d = (cm_an.get(cm_key) or {})
    h20 = d.get("horizons", {}).get("20", {})

    if is_market_bet and dac_dir is not None:
        dr = dac_dir.get("direction_hit_rate")
        n_s = dac_dir.get("n_direction_settled", 0)
        n_p = dac_dir.get("n_direction_pending", 0)
        dr_str = f"{dr:.0f}%" if dr is not None else "—"
        return (f'<div class="lsect3"><div class="lsect3-hdr">預測準度（大盤方向）</div>'
                f'<div class="pstats" style="grid-template-columns:repeat(2,1fr)">'
                f'<div class="pstat"><div class="pstat-v" style="color:#c0392b">{dr_str}</div>'
                f'<div class="pstat-l">方向命中率</div></div>'
                f'<div class="pstat"><div class="pstat-v">{n_s}已結算</div>'
                f'<div class="pstat-l">{n_p} 待定</div></div>'
                f'</div></div>')

    hr = h20.get("hit_rate"); bm = h20.get("beat_mkt")
    hr_str = f"{hr:.0f}%" if hr is not None else "—"
    bm_str = f"{bm:.0f}%" if bm is not None else "—"
    bm_col = "#1a8754" if (bm is not None and bm >= 50) else "#c0392b"
    box = (f'<div class="lsect3"><div class="lsect3-hdr">預測準度 · 做多</div>'
           f'<div class="pstats" id="stats_{uid}" style="grid-template-columns:repeat(2,1fr)">'
           f'<div class="pstat"><div class="pstat-v">{hr_str}</div>'
           f'<div class="pstat-l">命中率</div></div>'
           f'<div class="pstat"><div class="pstat-v" style="color:{bm_col}">{bm_str}</div>'
           f'<div class="pstat-l">贏大盤率</div></div>'
           f'</div></div>')
    # 看空腿（分開列；有看空才顯示）
    se = h20.get("short_excess_ann"); sh = h20.get("short_hit")
    if se is not None and sh is not None:
        se_col = "#1a8754" if se > 0 else "#c0392b"
        sh_col = "#1a8754" if sh >= 50 else "#c0392b"
        box += (f'<div class="lsect3" style="margin-top:8px"><div class="lsect3-hdr">預測準度 · 看空（不放空，僅記準度）</div>'
                f'<div class="pstats" style="grid-template-columns:repeat(2,1fr)">'
                f'<div class="pstat"><div class="pstat-v" style="color:{sh_col}">{sh:.0f}%</div>'
                f'<div class="pstat-l">看空命中率</div></div>'
                f'<div class="pstat"><div class="pstat-v" style="color:{se_col}">{se:+.1f}%</div>'
                f'<div class="pstat-l">看空年化超額</div></div>'
                f'</div></div>')
    return box


# ── 八欄預測紀錄表 ────────────────────────────────────────
def calls_table(cm_key, bench_name, mode="full", uid=None):
    """渲染統一八欄表。
    若紀錄帶 byh（多天期）且給 uid → 產生空 tbody，前端 renderTable 依持有天數即時填。
    否則（is_market_bet / explicit 窗）→ 直接靜態渲染。"""
    cr = (cm_an.get(cm_key) or {}).get("call_results") or []
    if not cr:
        return ""
    def _icon(h):
        return ('<span style="color:#1a8754;font-weight:700">✓</span>' if h == "hit"
                else '<span style="color:#c0392b;font-weight:700">✗</span>' if h == "miss"
                else '<span style="color:#aab0b8">⏳</span>')
    def _num(v, color=False):
        if v is None:
            return "⏳"
        s = f"{v:+.1f}%"
        if color:
            c = "#1a8754" if v > 0 else ("#c0392b" if v < 0 else "#6b7280")
            return f'<span style="color:{c}">{s}</span>'
        return s
    rows = ""
    for r in cr:
        cls = ' class="pend"' if r["hit"] == "pending" else ""
        dcol = "#1a8754" if r["dir"] == "看多" else "#c0392b"
        rows += (f'<tr{cls}><td>{r["date"][:10]}</td>'
                 f'<td class="rsum" title="{r.get("full", r["summary"])}">{r["summary"]}</td>'
                 f'<td style="color:{dcol}">{r["dir"]}</td>'
                 f'<td>{r["period"]}</td>'
                 f'<td>{_num(r["strat"])}</td>'
                 f'<td>{_num(r["bench"])}</td>'
                 f'<td>{_num(r["excess"], color=True)}</td>'
                 f'<td>{_icon(r["hit"])}</td></tr>')
    note = ('<div class="rnote">代表天期固定 20 日（他未明示持有期）；完整 5/20/60/120/250 天期見上方選擇器。</div>'
            if mode == "topbottom" else
            '<div class="rnote">每筆用他自己講的時間窗結算；⏳ = 預測期未到，不計入命中率。</div>')
    hdr = (f'<tr><th>日期</th><th>預測摘要</th><th>方向</th><th>評估期間</th>'
           f'<th>策略</th><th>基準({bench_name})</th><th>超額</th><th>結果</th></tr>')
    return (f'<details class="sub"><summary>預測紀錄（{len(cr)} 筆）</summary>'
            f'{note}<div class="rtbl-wrap"><table class="rtbl">{hdr}{rows}</table></div></details>')


# ── 命中點陣（預測型共用：每點＝一條預言，綠中/紅錯/灰待定）────────
def dots_strip(cm_key, pending_cap=30):
    cr = (cm_an.get(cm_key) or {}).get("call_results") or []
    settled = sorted([r for r in cr if r.get("hit") in ("hit", "miss")],
                     key=lambda r: r["date"])
    n_pend = sum(1 for r in cr if r.get("hit") == "pending")
    if not settled and not n_pend:
        return ""
    d = "".join(
        f'<span class="dot" title="{r["date"][:7]}｜{r["summary"][:18]}" '
        f'style="background:{"#c0392b" if r["hit"]=="miss" else "#1a8754"}"></span>'
        for r in settled)
    show_p = min(n_pend, pending_cap)
    d += '<span class="dot" style="background:#dfe2e7"></span>' * show_p
    n_hit = sum(1 for r in settled if r["hit"] == "hit")
    more = (f'　＋{n_pend - show_p} 條待定未畫' if n_pend > show_p else "")
    legend = (f'<div class="rnote"><b style="color:#1a8754">●</b> 命中 {n_hit}　'
              f'<b style="color:#c0392b">●</b> 未中 {len(settled) - n_hit}　'
              f'<b style="color:#cfd4da">●</b> 待定 {n_pend}{more}'
              f'（每點＝一條預言、依時間排序）</div>')
    return f'{legend}<div class="dots">{d}</div>'


# ── 同一份逐筆底稿、兩種視角（第一部分=持倉/$，第二部分=命中）──────
def _ledger_flat_rows(cr):
    """flat call_results（explicit 窗 / market-bet）→ (持倉列 html, 命中列 html)。"""
    def _num(v, color=False):
        if v is None:
            return "⏳"
        s = f"{v:+.1f}%"
        if color:
            c = "#1a8754" if v > 0 else ("#c0392b" if v < 0 else "#6b7280")
            return f'<span style="color:{c}">{s}</span>'
        return s
    def _icon(h):
        return ('<span style="color:#1a8754;font-weight:700">✓</span>' if h == "hit"
                else '<span style="color:#c0392b;font-weight:700">✗</span>' if h == "miss"
                else '<span style="color:#aab0b8">⏳</span>')
    h1 = ""; h2 = ""
    for r in cr:
        cls = ' class="pend"' if r.get("hit") == "pending" else ""
        dcol = "#1a8754" if r["dir"] == "看多" else "#c0392b"
        act = "買進" if r["dir"] == "看多" else "轉現金"
        dt = r["date"][:10]; sm = r["summary"]; ft = r.get("full", sm)
        h1 += (f'<tr{cls}><td>{dt}</td><td class="rsum" title="{ft}">{sm}</td>'
               f'<td>{act}</td><td>{r["period"]}</td>'
               f'<td>{_num(r["strat"], True)}</td><td>{_num(r["bench"])}</td>'
               f'<td>{_num(r["excess"], True)}</td></tr>')
        h2 += (f'<tr{cls}><td>{dt}</td><td class="rsum" title="{ft}">{sm}</td>'
               f'<td style="color:{dcol}">{r["dir"]}</td><td>{r["period"]}</td>'
               f'<td>{_num(r["excess"], True)}</td><td>{_icon(r["hit"])}</td></tr>')
    return h1, h2


def ledger_tables(cm_key, uid, bench_name, mode="full"):
    """回傳 (part1_持倉表, part2_命中表)。
    多天期(byh) → 空 tbody，前端 renderTable 依天數即時填。
    flat(explicit 窗 / market-bet) → 直接 server 端渲染（無天數鈕、用他自己講的窗）。"""
    cr = (cm_an.get(cm_key) or {}).get("call_results") or []
    if not cr:
        return "", ""
    # flat（explicit 窗）：market-bet，$ 與紀錄同窗、但無天數鈕
    if not any("byh" in r for r in cr):
        rows1, rows2 = _ledger_flat_rows(cr)
        note1 = ('<div class="rnote">第一部分的 $ 是把<b>每筆預測</b>照他方向做、用<b>他自己講的時間窗</b>'
                 '逐日複利累積（看多＝買進該資產、看跌＝轉現金）。下面就是逐筆持倉賺賠——'
                 '<b>跟下方命中紀錄同一批、同樣的窗</b>（$ 是逐日水位、非逐筆相加）。</div>')
        hdr1 = (f'<tr><th>日期</th><th>立場（賭哪個資產）</th><th>動作</th><th>他講的期間</th>'
                f'<th>策略報酬</th><th>基準({bench_name})</th><th>超額</th></tr>')
        t1 = (f'<details class="sub"><summary>持倉紀錄（{len(cr)} 筆，這就是 $ 怎麼來的）</summary>'
              f'{note1}<div class="rtbl-wrap"><table class="rtbl">{hdr1}{rows1}</table></div></details>')
        note2 = ('<div class="rnote">純看每筆<b>方向對不對</b>（賭的資產有沒有照他講的方向走），'
                 '這就是上方命中率怎麼數的。⏳＝預測期未到。</div>')
        hdr2 = (f'<tr><th>日期</th><th>立場摘要</th><th>方向</th><th>他講的期間</th>'
                f'<th>超額</th><th>結果</th></tr>')
        t2 = (f'<details class="sub"><summary>命中紀錄（{len(cr)} 筆，自己對）</summary>'
              f'{note2}<div class="rtbl-wrap"><table class="rtbl">{hdr2}{rows2}</table></div></details>')
        return t1, t2
    scope = ("最神／最雷各 5 筆（依 20 日超額挑選）" if mode == "topbottom"
             else f"全部 {len(cr)} 筆立場逐筆列出")
    _sum1 = (f"持倉紀錄（展示 {len(cr)} 筆：最神／最雷各 5，$ 由全部喊盤累積）"
             if mode == "topbottom" else
             f"持倉紀錄（全部 {len(cr)} 筆，這就是 $ 怎麼來的）")
    _sum2 = (f"命中紀錄（展示 {len(cr)} 筆：最神／最雷各 5）"
             if mode == "topbottom" else
             f"命中紀錄（全部 {len(cr)} 筆，自己對）")
    data = json.dumps({"rows": cr, "bench": bench_name}, ensure_ascii=False)
    embed = f'<script>_tbl[{json.dumps(uid)}]={data};</script>'

    # 第一部分：持倉/$ 視角（看他每筆買什麼、這筆賺賠多少 $）—— 無對錯欄
    note1 = ('<div class="rnote">第一部分的 $ 就是把<b>每一筆持倉</b>按 call 頻率加權累積起來：'
             '看多＝買進該 ETF、看空＝轉現金。下面每筆的「策略報酬」就是這筆持倉賺賠，'
             f'<b>跟著上方「持有天數」按鈕變</b>（{scope}，⏳＝該天期未到期）。</div>')
    hdr1 = (f'<tr><th>日期</th><th>立場（買什麼）</th><th>動作</th><th>持有期間</th>'
            f'<th>策略報酬</th><th>基準({bench_name})</th><th>超額</th></tr>')
    t1 = (f'<details class="sub"><summary>{_sum1}</summary>'
          f'{note1}<div class="rtbl-wrap"><table class="rtbl">{hdr1}'
          f'<tbody id="tb1_{uid}"></tbody></table></div></details>{embed}')

    # 第二部分：命中視角（純看每筆方向對不對）—— 有對錯欄
    note2 = ('<div class="rnote">純看每筆<b>方向對不對</b>（超額 &gt; 0 算命中），這就是上方命中率怎麼數的。'
             f'<b>跟著上方「持有天數」按鈕變</b>（{scope}，⏳＝該天期未到期）。</div>')
    hdr2 = (f'<tr><th>日期</th><th>立場摘要</th><th>方向</th><th>評估期間</th>'
            f'<th>超額</th><th>結果</th></tr>')
    t2 = (f'<details class="sub"><summary>{_sum2}</summary>'
          f'{note2}<div class="rtbl-wrap"><table class="rtbl">{hdr2}'
          f'<tbody id="tb2_{uid}"></tbody></table></div></details>')
    return t1, t2


# ── 依模式產出對應統計盒（看多頁=做多數據、看空頁=看空數據、雙向頁=雙向）──
def _pbox(hdr, items):
    """items: list of (value_str, color, label)。cols 依數量。"""
    cols = len(items)
    cells = "".join(
        f'<div class="pstat"><div class="pstat-v" style="color:{c}">{v}</div>'
        f'<div class="pstat-l">{l}</div></div>' for v, c, l in items)
    return (f'<div class="lsect3"><div class="lsect3-hdr">{hdr}</div>'
            f'<div class="pstats" style="grid-template-columns:repeat({cols},1fr)">{cells}</div></div>')


def mode_stats(cm_key, is_market_bet=False):
    """回傳 {long, both, short} 各自的統計盒 HTML。"""
    a = cm_an.get(cm_key, {})
    h20 = a.get("horizons", {}).get("20", {})
    out = {}
    if is_market_bet:
        def dbox(hdr, rate, n, col):
            r = f"{rate:.0f}%" if rate is not None else "—"
            return _pbox(hdr, [(r, col, "方向命中率"), (f"{n}", "inherit", "已結算筆數")])
        bull = a.get("bull_dir_hit"); bear = a.get("bear_dir_hit"); allr = a.get("direction_hit_rate")
        out["long"]  = dbox("看漲方向", bull, a.get("n_bull_settled", 0),
                            "#1a8754" if (bull or 0) > 55 else ("#c0392b" if (bull or 0) < 45 else "inherit"))
        out["short"] = dbox("看跌方向", bear, a.get("n_bear_settled", 0),
                            "#1a8754" if (bear or 0) > 55 else ("#c0392b" if (bear or 0) < 45 else "inherit"))
        out["both"]  = dbox("整體方向（看漲＋看跌）", allr, a.get("n_direction_settled", 0),
                            "#c0392b" if (allr or 0) < 50 else "#1a8754")
        return out
    # 個股/產業：做多三格、看空兩格、雙向說明
    hr = h20.get("hit_rate"); bm = h20.get("beat_mkt")
    out["long"] = _pbox("做多準度", [
        (f"{hr:.0f}%" if hr is not None else "—", "inherit", "命中率"),
        (f"{bm:.0f}%" if bm is not None else "—", "#1a8754" if (bm or 0) >= 50 else "#c0392b", "贏大盤率")])
    se = h20.get("short_excess_ann"); sh = h20.get("short_hit")
    if se is not None and sh is not None:
        out["short"] = _pbox("看空準度（不放空，僅記準度）", [
            (f"{sh:.0f}%", "#1a8754" if sh >= 50 else "#c0392b", "看空命中率"),
            (f"{se:+.1f}%", "#1a8754" if se > 0 else "#c0392b", "看空年化超額")])
    out["both"] = ('<div class="note" style="margin:0">雙向＝做多買進＋看空放空（假設你會放空）。'
                   '$ 終值已反映於上方；他看空多半看錯時，雙向通常低於純做多。</div>')
    return out


# ── 看多/雙向/看空 三模式切換區塊 ──────────────────────────
def _duel(follow, bench, bench_label):
    win = follow > bench
    cls = "pos" if win else ("neg" if follow < bench else "flat")
    return (f'<div class="pduel"><div class="pside">'
            f'<div class="pv {cls}">${follow:,.0f}</div><div class="pl">$100 跟他</div></div>'
            f'<div class="pvs">vs</div><div class="pside">'
            f'<div class="pv mkt">${bench:,.0f}</div><div class="pl">$100 買{bench_label}</div></div></div>')


def mode_block(uid, bench, bench_label, modes_h20, mcurve, base_verdict, stats=None):
    """三模式切換：每個分頁＝該模式的 $圖+判決+對應統計盒（看多頁只有做多數據…）。"""
    stats = stats or {}
    mlong = modes_h20.get("long", {})
    mboth = modes_h20.get("both"); mshort = modes_h20.get("short")
    long_follow = mlong.get("follow_end") or 0
    long_curve  = mlong.get("curve") or [1, 1]
    bf = (mboth or {}).get("follow_end"); sf = (mshort or {}).get("follow_end")

    def pane(mode, follow, curve, verdict, hint, on):
        cls = "mpane on" if on else "mpane"
        hint_html = f'<div class="mhint">{hint}</div>' if hint else ""
        # 第一部分只放策略：$對比+曲線+判決（準度盒移到第二部分）
        return (f'<div class="{cls}" id="m_{uid}_{mode}">'
                f'{_duel(follow, bench, bench_label)}{spark(curve, mcurve)}'
                f'{hint_html}<div class="pverdict">{verdict}</div></div>')

    # 無看空 → 不切換（仍把做多統計盒放進來）
    if not mboth or not mshort:
        return pane("long", long_follow, long_curve, base_verdict, "", True)

    v_both = (f"假設看多買進＋看空也放空：${bf:,.0f} vs 買大盤 ${bench:,.0f}。"
              + ("加進看空反而扣分（他看空多半看錯）" if bf < long_follow else "看空也加分"))
    v_short = f"假設只放空他看壞的：${sf:,.0f} vs 買大盤 ${bench:,.0f}。"
    HINT = "⚠️ 假設你會放空（散戶通常不會），純看他方向判斷值不值錢"
    tog = (f'<div class="mtog">'
           f'<button class="on" onclick="setMode(\'{uid}\',\'long\',this)">看多（實際）</button>'
           f'<button onclick="setMode(\'{uid}\',\'both\',this)">雙向</button>'
           f'<button onclick="setMode(\'{uid}\',\'short\',this)">看空</button></div>')
    panes = (pane("long", long_follow, long_curve, base_verdict, "", True)
             + pane("both", bf, mboth["curve"], v_both, HINT, False)
             + pane("short", sf, mshort["curve"], v_short, HINT, False))
    return tog + panes


# ── 卡片骨架：拆成「名牌(牆上)」+「浮層(點開)」兩部分 ──────────
def _slug(s):
    import re as _re
    return _re.sub(r"[^0-9A-Za-z一-鿿]", "", s)

def card(typ, name, sample, follow, bench, verdict, spark_svg,
         stats3_html="", detail_html="", bonus_html="", table_html="",
         search_name=None, bench_label="大盤", mode_data=None, uid=None, p1=None,
         table1_html=""):
    """回傳 (tile_html, modal_html)。tile=牆上極簡名牌；modal=點開的完整卡。"""
    t = TYPE[typ]
    ratio = (follow / bench - 1) * 100 if bench else 0
    diff_cls = "pos" if follow > bench else ("neg" if follow < bench else "flat")
    mid = _slug(search_name or name)
    cm = cm_an.get(name) or {}
    hz = cm.get("horizons") or {}
    is_mb = bool(cm.get("is_market_bet"))
    has_short = any((hz.get(h) or {}).get("has_short") for h in hz)
    if not uid:
        uid = _slug(name)
    avail = [h for h in ["5", "20", "60", "120", "250"] if h in hz]
    # 審計摘要 placeholder（第二階段補內容）
    import os as _os2
    _audit_p = f"audit/{_slug(name)}.md"
    if _os2.path.exists(_audit_p):
        _audit_body = open(_audit_p, encoding="utf-8").read()
    else:
        _audit_body = '<span style="color:var(--mut)">審計內容待補（第二階段：頻道類型理由、字幕可用率、使用標的、判決規則應用）</span>'
    import re as _re_audit
    _audit_tip = (_re_audit.sub("<[^>]+>", "", _audit_body)
                  .replace('"', "”").replace("\n", " ").strip())

    # ── 名牌（牆上）：分類 + $對比 + 迷你線 + 一句判決 ──
    tile = f"""
    <article class="ncard" data-name="{search_name or name}" data-type="{typ}" data-excess="{ratio:.2f}"
             onclick="openModal('{mid}')">
      <div class="ncard-head"><span class="ncard-name">{name}</span></div>
      <div class="ncard-duel"><span class="pv {diff_cls}">${follow:,.0f}</span>
        <span class="ncard-vs">vs</span><span class="pv mkt">${bench:,.0f}</span></div>
      <div class="ncard-spark">{spark_svg}</div>
      <div class="ncard-verdict">{verdict}</div>
    </article>"""
    _sidebar_items.append({"uid": uid or mid, "mid": mid, "name": name,
                            "label": t["label"], "type": typ,
                            "follow": follow, "bench": bench, "diff_cls": diff_cls})

    # ── 浮層（點開）：統一控制條 + 兩部分，全部由 cmRender(uid) 即時重繪 ──
    def _hbtn(h):
        on = ' class="on"' if h == "20" else ''
        return f'<button onclick="setH(\'{uid}\',\'{h}\',this)"{on}>{h}日</button>'
    def _dbtn(key, label, on):
        c = ' class="on"' if on else ''
        return f'<button onclick="setDir(\'{uid}\',\'{key}\',this)"{c}>{label}</button>'
    def _bbtn(key, label, on):
        c = ' class="on"' if on else ''
        return f'<button onclick="setBase(\'{uid}\',\'{key}\',this)"{c}>{label}</button>'
    ctrl = ""
    # 天數：只有資產卡（喊單/總經）有意義；大盤擇時型（賭大盤方向）終值不隨天數變 → 不顯示
    if not is_mb and len(avail) > 1:
        ctrl += (f'<div class="ctrlrow"><span class="ctrll">持有天數</span>'
                 f'<div class="ppick">{"".join(_hbtn(h) for h in avail)}</div></div>')
    # 方向：兩部分共用一個
    if is_mb and (cm.get("bull_dir_hit") is not None or cm.get("bear_dir_hit") is not None):
        ctrl += (f'<div class="ctrlrow"><span class="ctrll">預測方向</span><div class="mtog">'
                 f'{_dbtn("both","整體",True)}{_dbtn("long","看漲",False)}{_dbtn("short","看跌",False)}'
                 f'</div></div>')
    elif (not is_mb) and has_short:
        ctrl += (f'<div class="ctrlrow"><span class="ctrll">方向</span><div class="mtog">'
                 f'{_dbtn("long","做多",True)}{_dbtn("both","雙向",False)}{_dbtn("short","看空",False)}'
                 f'</div></div>')
    # 頂部控制條（影響第一＋第二部分）收進淡灰面板
    if ctrl:
        ctrl = f'<div class="ctrlpanel">{ctrl}</div>'
    # 基準鈕（只影響第二部分）→ 不放頂部，移到第二部分標題旁
    _BASE_LABELS = {"mkt": "比大盤", "dir": "方向對沒", "profit": "有賺沒"}
    h20_any = (hz.get("20") or hz.get(avail[0]) if avail else {}) or {}
    _bl_opts = ["dir", "mkt"] if is_mb else (["mkt", "profit"] if h20_any.get("hit_rate") is not None else ["mkt"])
    _bl_def  = "dir" if is_mb else "mkt"
    base_ctrl = ""
    if len(_bl_opts) > 1:
        base_ctrl = ('<span class="ctrll">基準</span><div class="mtog">'
                     + "".join(_bbtn(o, _BASE_LABELS[o], o == _bl_def) for o in _bl_opts)
                     + '</div>')

    SHORT_HINT = "⚠️ 假設你會放空（散戶通常不會）—— $ 數字僅供方向判斷參考"
    # 預言型：頂部判決句跟方向鈕連動（看漲腿／看跌腿／整體各自的方向命中率），與第二部分一致
    if is_mb:
        from verdict_rules import verdict_market_dir as _vmd
        mb_verdicts = {
            "both":  _vmd(cm.get("direction_hit_rate"), cm.get("n_direction_settled", 0)),
            "long":  _vmd(cm.get("bull_dir_hit"), cm.get("n_bull_settled", 0)),
            "short": _vmd(cm.get("bear_dir_hit"), cm.get("n_bear_settled", 0)),
        }
    meta = {"is_mb": is_mb, "has_short": has_short, "bench_label": bench_label,
            "dir0": "both" if is_mb else "long",
            "baseline": {"default": _bl_def, "options": _bl_opts},
            "verdicts": {
                "long":  verdict,
                "both":  SHORT_HINT if has_short else verdict,
                "short": SHORT_HINT,
            } if not is_mb else mb_verdicts}
    if is_mb:
        # 各方向的待定數（pending 依方向拆，修正比例條把待定歸零的問題）
        _cr = cm.get("call_results") or []
        _bull_pend = sum(1 for r in _cr if r.get("dir") == "看多" and r.get("hit") == "pending")
        _bear_pend = sum(1 for r in _cr if r.get("dir") == "看空" and r.get("hit") == "pending")
        meta["dir"] = {
            "bull": {"rate": cm.get("bull_dir_hit"), "n": cm.get("n_bull_settled", 0), "pend": _bull_pend},
            "bear": {"rate": cm.get("bear_dir_hit"), "n": cm.get("n_bear_settled", 0), "pend": _bear_pend},
            "all":  {"rate": cm.get("direction_hit_rate"), "n": cm.get("n_direction_settled", 0),
                     "pend": cm.get("n_direction_pending", 0)},
        }
        meta["pend"] = cm.get("n_direction_pending", 0)
        # 不再寫死 p1：市場擇時型第一部分改吃 hz[h].modes[dir]（引擎已算 long/both/short
        # 三條策略曲線），讓「預測方向」鈕同時驅動第一部分（$／曲線）與第二部分（準度）。
        # 基準腿仍用全期「一直持有」(r.mkt_end)，各方向都跟同一條被動線比＝公平。
    # 第三部分：體檢表（所有分析師，依天數動態切換）
    _cr_all = cm.get("call_results") or []
    meta["health"] = _compute_health(_cr_all, avail)
    embed = (f'<script>_cm[{json.dumps(uid)}]={json.dumps(hz, ensure_ascii=False)};'
             f'_cmM[{json.dumps(uid)}]={json.dumps(meta, ensure_ascii=False)};'
             f'(window._inits=window._inits||[]).push({json.dumps(uid)});</script>')

    p1_block = (f'<div class="pduel" id="du_{uid}"></div>'
                f'<div class="pspark" id="sp_{uid}"></div>'
                f'<div class="l1-risk" id="dd_{uid}"></div>'
                f'<div class="pverdict" id="vd_{uid}"></div>'
                f'<div id="ci_{uid}"></div>')
    detail_block = (f'<details class="pdetail" open><summary>細節與證據</summary>{detail_html}</details>'
                    if detail_html else "")
    _base_row = (f'<div class="psec-base">{base_ctrl}</div>' if base_ctrl else "")
    part2_block = (f'<div class="psec-hdr2"><span class="psec-hdr">第二部分 · 方向預測準度'
                   f'<span class="info" data-tip="純看他「每次猜對沒」——只算準度，不影響上方 $。持有天數、方向鈕沿用上方控制條。">i</span></span>{_base_row}</div>'
                   f'<div id="p2_{uid}"></div>{table_html}')
    part3_block = (f'<div class="psec-hdr">第三部分 · 這是本事，還是運氣？'
                   f'<span class="info" data-tip="四個角度拆解他的贏法——命中率、報酬集中度、贏輸幅度、每筆期望——幫你判斷是真本事還是剛好。　◆ 為什麼這樣評（審計）：{_audit_tip}">i</span></div>'
                   f'<div id="p3_{uid}"></div>'
                   f'{bonus_html}')
    modal = f"""
    <div class="modal" id="modal-{mid}" onclick="if(event.target===this)closeModal()">
      <div class="modal-box">
        <button class="modal-x" onclick="closeModal()">✕</button>
        <div class="pmod pmod-head">
          <div class="phead"><div>
              <div class="pname">{name}</div><div class="psample">{sample}</div>
              <div class="psample psample-scope">卡內數字＝<b>完整追蹤期</b>（可切持有天數）；排行榜為<b>近12個月</b>，兩者口徑不同、不會相等。</div>
            </div></div>
          {ctrl}
        </div>
        <div class="pmod">
          <div class="psec-hdr">第一部分 · 策略表現<span class="psec-q">（$100 跟他 vs $100 買{bench_label}，全期）</span><span class="info" data-tip="這裡是『完整追蹤期』的終值（見上方名字下的日期），跟排行榜『近12個月』那組數字口徑不同、不會相等。算法：把他每筆預測照方向、按 call 頻率加權累積成 $100 的淨值，對照同期綜合大盤。看空＝不買（不放空），只記準度、不混入做多顯著性；各卡回測期／市場不同，終值不能跨卡比。">i</span></div>
          {p1_block}
          {detail_block}
          {table1_html}
        </div>
        <div class="pmod">
          {part2_block}
        </div>
        <div class="pmod">
          {part3_block}
        </div>
        {embed}
      </div>
    </div>"""
    return tile, modal

# ── CI bar（含 FDR 標記，與 JS 動態版一致）───────────────
def _ci_html(a, lo, hi, p, fdr=False, raw=False):
    if a is None or lo is None or hi is None:
        return '<div class="rnote">此人以看空為主，無「做多超額」可估；看空準度見下方。</div>'
    covers0 = lo <= 0 <= hi
    col = "#6b7280" if covers0 else ("#1a8754" if a > 0 else "#c0392b")
    sc_ = lambda v: 50 + max(-50, min(50, v/1.6))
    _raw_tip = '通過單次 t 檢定但未過多重比較校正，不代表績效好壞，只代表跟大盤有落差'
    mark = (' <b style="color:#1a8754">✓校正後存活</b>' if fdr
            else (f' <span style="color:#8a8f98" title="{_raw_tip}">*未校正顯著{"（跑輸）" if raw and a is not None and a < 0 else ""}</span>' if raw else ''))
    return (f'<div class="ci-wrap"><div class="ci-row">'
            f'<span>持有期間年化超額 {a:+.1f}%（p={p:.3f}）{mark}</span>'
            f'<span>95% CI [{lo:+.0f}%, {hi:+.0f}%]</span></div>'
            f'<div class="ci-track"><div class="ci-zero"></div>'
            f'<div class="ci-range" style="left:{sc_(lo)}%;width:{min(100,max(1,(hi-lo)/1.6))}%;background:{col}33;border:1.5px solid {col}"></div>'
            f'<div class="ci-dot" style="left:{sc_(a)}%;background:{col}"></div></div></div>')

def ci_bar(k):
    return _ci_html(k["excess_ann"], k["ci_lo"], k["ci_hi"], k["p"])

# ── 統一持有期選擇器（calendar-time，已驗證引擎）─────────
def cal_picker(analyst_key, uid):
    d = (cm_an.get(analyst_key) or {}).get("horizons", {})
    if not d:
        return ""
    def _btn(h):
        on = ' class="on"' if h == "20" else ""
        return f'<button onclick="setPeriod(\'{uid}\',\'{h}\',this)"{on}>{h}日</button>'
    btns = "".join(_btn(h) for h in ["5","20","60","120","250"] if h in d)
    d0 = d.get("20") or next(iter(d.values()))
    ci0 = _ci_html(d0["excess_ann"], d0["ci_lo"], d0["ci_hi"], d0["p"],
                   d0.get("fdr_sig"), d0.get("raw_sig"))
    return (f'<div class="ppick" id="pp_{uid}">{btns}</div>'
            f'<div id="ci_{uid}">{ci0}</div>'
            f'<script>_cm["{uid}"]={json.dumps(d, ensure_ascii=False)};</script>')

# ── 單一通用卡片：加任何分析師都自動長卡片，無型別特例（人不分類）────
#   差異全由 registry/資料欄推導：基準標籤由 market、ledger 取樣由「筆數多寡」。
_BENCH_BY_MARKET = {
    "台股": ("TAIEX", "綜合大盤"),
    "美股": ("SPY",   "綜合大盤"),
    "多資產": ("配對", "綜合大盤"),
}
def analyst_card(nm):
    a = cm_an.get(nm)
    if not a or not a.get("horizons"):
        return ""
    h20 = a["horizons"].get("20", {})
    follow = h20.get("follow_end", 100)
    bench  = h20.get("mkt_end", 100)
    ncalls = (a.get("coverage") or {}).get("n_calls", 0)
    market = a.get("market", "")
    mb = bool(a.get("is_market_bet"))          # 由 call 組成推導的顯示提示（見引擎）
    uid = _slug(nm)
    # 追蹤起始～最新（引擎存的全量 date_range；避免用 topbottom 截斷後的 call_results）
    _dr = a.get("date_range")
    _span = f" · 追蹤 {_dr[0][:7]}～{_dr[1][:7]}" if _dr else ""
    bench_tk, bench_label = _BENCH_BY_MARKET.get(market, ("SPY", "大盤"))
    mode = "topbottom" if (market == "台股" and not mb) else "full"
    t1, t2 = ledger_tables(nm, uid, bench_tk, mode=mode)
    curve = h20.get("curve", [1, 1]); mcurve = h20.get("mcurve", [1, 1])
    return card("myst" if mb else "call", nm,
                f"{ncalls} 次喊盤 · {market}{_span}", follow, bench,
                gen_verdict(a), spark(curve, mcurve),
                table_html=t2, table1_html=t1, uid=uid, bench_label=bench_label,
                search_name=nm, p1={"curve": curve, "mcurve": mcurve})

# ── 組卡片（每張回傳 (名牌, 浮層)）：全體分析師走同一函式，依終值/大盤比排序 ──
def _kol_ratio(nm):
    h = cm_an[nm].get("horizons", {}).get("20", {})
    f, b = h.get("follow_end", 100), h.get("mkt_end", 100)
    return f / b if b else 0
_ordered = sorted([nm for nm, a in cm_an.items() if a.get("horizons")],
                  key=lambda nm: -_kol_ratio(nm))
_built = [analyst_card(nm) for nm in _ordered]
_built = [b for b in _built if b]                     # 去掉空字串（資料缺）
tiles_html  = "".join(b[0] for b in _built if isinstance(b, tuple))
modals_html = "".join(b[1] for b in _built if isinstance(b, tuple))
cards_html = tiles_html
n_total = len(_ordered)

# ── 第二頁 Sidebar HTML ──────────────────────────────────
def _sb_item(it, first=False):
    diff = it["follow"] - it["bench"]
    sign = "+" if diff >= 0 else ""
    cls = it["diff_cls"]
    on = ' on' if first else ''
    _uid, _mid = it["uid"], it["mid"]
    return (f'<button class="sb-item{on}" data-uid="{_uid}" data-type="{it["type"]}" data-mid="{_mid}" '
            f"onclick=\"selectAnalyst('{_uid}','{_mid}')\">"
            f'<span class="sb-name">{it["name"]}</span>'
            f'<span class="sb-val {cls}">{sign}${diff:,.0f}</span>'
            f'</button>')
sidebar_html = "".join(_sb_item(it, i == 0) for i, it in enumerate(_sidebar_items))
_first_uid = _sidebar_items[0]["uid"] if _sidebar_items else ""
_first_mid = _sidebar_items[0]["mid"] if _sidebar_items else ""

# ── 自選淨值實驗台：全體淨值資料（給前端疊圖）────────────
def _type_of(name, market, is_mb):
    if is_mb or "擇時" in (cm_an.get(name, {}).get("label") or ""):
        return "myst"
    return "macro" if market == "美股" else "call"

def _bench_of(nm, market):
    if market == "台股":
        return "TWSE", "綜合大盤"
    if nm == "吳昌華":
        return "BASKET", "五資產等權"
    return "SPY", "美股 S&P 500"

wall_data = []
for nm, a in cm_an.items():
    h20 = a.get("horizons", {}).get("20", {})
    cur = (h20.get("modes", {}).get("long", {}) or {}).get("curve") or h20.get("curve")
    mcur = h20.get("mcurve"); dts = h20.get("dates")
    if not cur or not mcur or not dts or h20.get("follow_end") is None:
        continue
    c0 = cur[0] or 1; m0 = mcur[0] or 1
    bkey, blabel = _bench_of(nm, a.get("market", ""))
    wall_data.append({
        "name": nm,
        "type": _type_of(nm, a.get("market", ""), a.get("is_market_bet")),
        "market": a.get("market", ""),
        "curve":  [round(v / c0 * 100, 2) for v in cur],     # 正規化 $100 起
        "mcurve": [round(v / m0 * 100, 2) for v in mcur],    # 大盤同樣 $100 起
        "dates":  dts,
        "bkey": bkey, "blabel": blabel,
        "follow": h20.get("follow_end"),
        "mkt": h20.get("mkt_end"),
        "capm": h20.get("capm"),
        "is_mb": bool(a.get("is_market_bet")),
    })
# 喊買前後 ±20 日走勢：改由 cm 即時算（rec["event"]），不再讀凍結 event_study.json
_ev = {nm: a["event"] for nm, a in cm_an.items() if a.get("event")}
wall_json = json.dumps(wall_data, ensure_ascii=False)
event_json = json.dumps(_ev, ensure_ascii=False)

# ── 整體統計頁資料 ─────────────────────────────────────
_kol_names = [nm for nm,x in cm_an.items() if not x.get("is_market_bet") and nm != "股癌（謝孟恭）"]
_mb_names   = [nm for nm,x in cm_an.items() if x.get("is_market_bet")]

# Block 3: FDR 判決表（個股選股型 + 股癌，按 $follow 降序）
_verdict_rows = []
for nm, x in cm_an.items():
    if x.get("is_market_bet"): continue
    h20 = x.get("horizons", {}).get("20", {})
    if h20.get("follow_end") is None: continue
    fdr = any(s.get("fdr_sig") for s in x.get("horizons", {}).values())
    raw = any(s.get("raw_sig") for s in x.get("horizons", {}).values())
    if fdr:   verdict_key = "fdr"
    elif raw: verdict_key = "raw"
    else:     verdict_key = "none"
    _verdict_rows.append({
        "name": nm,
        "follow": round(h20["follow_end"]),
        "mkt": round(h20["mkt_end"] or 0),
        "excess_ann": round(h20.get("excess_ann") or 0, 1),
        "verdict": verdict_key,
    })
_verdict_rows.sort(key=lambda r: -r["follow"])

# Block 4: 追漲證據（喊買前 20 日漲幅）
_runup_rows = []
for nm in list(_kol_names) + ["股癌（謝孟恭）"]:
    ev_d = _ev.get(nm)
    if not ev_d: continue
    days, path = ev_d["days"], ev_d["path"]
    try:
        ru = path[days.index(0)] - path[days.index(-20)]
    except ValueError:
        continue
    _runup_rows.append({"name": nm, "runup": round(ru, 1)})
_runup_rows.sort(key=lambda r: -r["runup"])

# Block 5: CAPM α 散布
_alpha_rows = []
for nm in _kol_names + ["股癌（謝孟恭）"]:
    h20 = cm_an.get(nm, {}).get("horizons", {}).get("20", {})
    capm = h20.get("capm")
    if capm:
        _alpha_rows.append({"name": nm, "alpha": capm["alpha"],
                             "market": capm["market"], "follow": capm["follow"]})

# Block 6: 天期敏感度（個股選股型 KOL，排除股癌）
_sens_rows = []
for h in ["5", "20", "60", "120", "250"]:
    exs, raws, fdrs = [], 0, 0
    for nm in _kol_names:
        hz = cm_an[nm]["horizons"].get(h, {})
        if hz.get("excess_ann") is not None:
            exs.append(hz["excess_ann"])
        if hz.get("raw_sig"): raws += 1
        if hz.get("fdr_sig"): fdrs += 1
    _sens_rows.append({
        "h": h,
        "avg_excess": round(sum(exs)/len(exs), 1) if exs else None,
        "raw_sig": raws, "fdr_sig": fdrs, "n": len(exs),
    })

# 方案B：群組層級指標（總覽儀表板）+ α 保留逐人
def _h20(nm): return cm_an.get(nm, {}).get("horizons", {}).get("20", {})
def _runup_of(nm):
    ev = _ev.get(nm)
    if not ev: return None
    try:
        return round(ev["path"][ev["days"].index(0)] - ev["path"][ev["days"].index(-20)], 1)
    except (ValueError, KeyError):
        return None
def _beat_of(nm):
    if cm_an.get(nm, {}).get("is_market_bet"): return None
    cr = (cm_an.get(nm) or {}).get("call_results") or []
    if not cr: return None
    h = _compute_health(cr, ["20"]).get("20")
    return h.get("beat") if h else None
def _gavg(names, fn):
    vals = [fn(nm) for nm in names]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

_groups = [
    ("個股選股型", _kol_names),
    ("產業主題型", ["股癌（謝孟恭）"]),
    ("大盤擇時型", _mb_names),
]
_metric_groups = [
    {
        "group": gname,
        "n": len(names),
        "final": _gavg(names, lambda nm: _h20(nm).get("follow_end")),
        "mkt": _gavg(names, lambda nm: _h20(nm).get("mkt_end")),
        "excess_ann": _gavg(names, lambda nm: _h20(nm).get("excess_ann")),
        "runup": _gavg(names, _runup_of),
        "winrate": _gavg(names, _beat_of),
    }
    for gname, names in _groups
]

# ── 動態排行榜：逐人列 ─────────────────────────────────
_type_map = {nm: "call" for nm in _kol_names}
_type_map["股癌（謝孟恭）"] = "macro"
for nm in _mb_names: _type_map[nm] = "myst"
_runup_map = {r["name"]: r["runup"] for r in _runup_rows}
_verdict_map = {r["name"]: r["verdict"] for r in _verdict_rows}

def _build_table_row(nm):
    x = cm_an.get(nm, {})
    is_mb = x.get("is_market_bet", False)
    byh = {}
    for h in ["5", "20", "60", "120", "250"]:
        hz = x.get("horizons", {}).get(h, {})
        capm = hz.get("capm") or {}
        if is_mb:
            byh[h] = {"final": hz.get("follow_end"), "mkt": hz.get("mkt_end"),
                      "excess_ann": hz.get("excess_ann"), "winrate": None, "alpha": None,
                      "hit_rate": x.get("direction_hit_rate")}
        else:
            cr = x.get("call_results") or []
            h_stat = _compute_health(cr, [h]).get(h) if cr else None
            byh[h] = {"final": hz.get("follow_end"), "mkt": hz.get("mkt_end"),
                      "excess_ann": hz.get("excess_ann"),
                      "winrate": h_stat.get("beat") if h_stat else None,
                      "alpha": capm.get("alpha"),
                      "hit_rate": hz.get("hit_rate")}
    # 真實樣本數：KOL 用 scorecard、擇時型用方向結算數、其餘用 call_results 筆數
    if nm in _kol_ncalls:
        n_calls = _kol_ncalls[nm]
    elif is_mb:
        n_calls = x.get("n_direction_settled", 0)
    else:
        n_calls = len(x.get("call_results") or [])
    ids = _row_ids.get(nm, {})
    _dr = x.get("date_range")
    return {"name": nm, "type": _type_map.get(nm, "call"),
            "uid": ids.get("uid"), "mid": ids.get("mid"),
            "runup": _runup_map.get(nm) if not is_mb else None,
            "dir_rate": x.get("direction_hit_rate") if is_mb else None,
            "n_settled": x.get("n_direction_settled", 0) if is_mb else None,
            "n_calls": n_calls,
            "span": f"{_dr[0][:7]}～{_dr[1][:7]}" if _dr else None,
            "excess_1y": x.get("excess_1y"),
            "raw_1y": x.get("raw_ret_1y"),
            "mkt_1y": x.get("mkt_ret_1y"),
            "mkt_blend": x.get("mkt_blend_1y"),
            "n_1y": x.get("n_calls_1y"),
            "fdr": _verdict_map.get(nm, "none"),
            "byh": byh}

_row_ids = {it["name"]: {"uid": it["uid"], "mid": it["mid"]} for it in _sidebar_items}
_table_rows = [_build_table_row(nm)
               for nm in _kol_names + ["股癌（謝孟恭）"] + _mb_names]

overview_json = json.dumps({
    "metric_groups": _metric_groups,
    "fdr_families": [
        {"name": "贏大盤（10 位個股型＋股癌）", "n": len(_kol_names) + 1,
         **cm_meta.get("kol_family", {})},
        {"name": "方向命中（大盤擇時型）", "n": len(_mb_names),
         **cm_meta.get("dac_family", {})},
    ],
    "verdict_rows": _verdict_rows,
    "runup_rows": _runup_rows,
    "alpha_rows": _alpha_rows,
    "sens_rows": _sens_rows,
    "mb_rows": [
        {"name": nm,
         "dir_rate": cm_an[nm].get("direction_hit_rate"),
         "n_settled": cm_an[nm].get("n_direction_settled", 0),
         "verdict": gen_verdict(cm_an[nm])}   # 統一規則表（方向＋擇時同一顯著門檻）
        for nm in _mb_names
    ],
    "table_rows": _table_rows,
}, ensure_ascii=False)


# ── Hero 儀表盤刊頭數字（全用真實資料即時算）──
import statistics as _st
def _med(xs):
    xs = [x for x in xs if x is not None]
    return _st.median(xs) if xs else None

_sp_names = _kol_names + ["股癌（謝孟恭）"]
_sp_pairs = [(_h20(nm).get("follow_end"), _h20(nm).get("mkt_end")) for nm in _sp_names]
_sp_pairs = [(f, m) for f, m in _sp_pairs if f is not None and m is not None]

_hero_n      = len(_kol_names) + 1 + len(_mb_names)   # 13
_hero_n_fdr  = sum(1 for v in _verdict_map.values() if v == "fdr")  # 撐過 FDR 的人數
_hero_med_f  = _med([f for f, m in _sp_pairs])        # 中位終值（股票型）
_hero_med_m  = _med([m for f, m in _sp_pairs])        # 中位大盤
# 方向命中率中位數（個股型用 hit_rate、擇時型用 direction_hit_rate）
_dir_hits = [_h20(nm).get("hit_rate") for nm in _sp_names]
_dir_hits += [cm_an[nm].get("direction_hit_rate") for nm in _mb_names]
_hero_med_dir = _med(_dir_hits)
# 喊買前追漲（個股選股型平均）
_hero_runup = _gavg(_kol_names, _runup_of)
# 訊號量（皆由 cm 即時算：台股 KOL 喊盤總數、股癌看多事件數）
_hero_n_calls   = sum((cm_an[nm].get("coverage") or {}).get("n_calls", 0) for nm in _kol_names)
_hero_n_sector  = (cm_an.get("股癌（謝孟恭）", {}).get("coverage") or {}).get("n_calls", 0)
# 判決句（隨資料自動更新：0 存活 → 沒有一位；否則列數字）
_hero_verdict_txt = "沒有一位" if _hero_n_fdr == 0 else f"僅 {_hero_n_fdr} 位"

# ── AI 問答範例 chips（依現有分析師名單即時生成，加人自動換）──────────
# 不再硬寫人名：從 _table_rows 挑「最活躍個股型 × 他最常喊的標的」「另一位 × 其標的」
# 「一位擇時/預言型 → 命中率」，加上一句與人無關的通用題。名單變則自動換。
import re as _re, collections as _collections

def _bare(nm):
    """去掉顯示名後的括號註記：股癌（謝孟恭）→ 股癌、國巨（2327）→ 國巨。"""
    return _re.sub(r"[（(].*", "", nm or "").strip() or nm

def _top_target(nm):
    """該分析師 call_results 中出現最多次的標的名（無則 None）。"""
    cnt = _collections.Counter()
    for c in (cm_an.get(nm, {}).get("call_results") or []):
        s = _bare((c.get("summary") or "").strip())
        if s:
            cnt[s] += 1
    return cnt.most_common(1)[0][0] if cnt else None

def _gen_ask_chips():
    call_rows = sorted([r for r in _table_rows if r["type"] == "call" and r["n_calls"]],
                       key=lambda r: r["n_calls"], reverse=True)
    mb_rows = [r for r in _table_rows if r["type"] != "call"]
    chips = ["誰的勝率最高"]                       # 通用題（永遠成立）
    for i, verb in ((0, "喊{t}賺了嗎"), (1, "怎麼看{t}")):
        if len(call_rows) > i:
            nm = call_rows[i]["name"]; tg = _top_target(nm)
            if tg:
                chips.append(f"{_bare(nm)}{verb.format(t=tg)}")
    if mb_rows:                                     # 擇時/預言型 → 問命中率（措辭中性，適用任一型）
        chips.append(f"{_bare(mb_rows[0]['name'])}命中率多少")
    # 去重 + 保底補通用題，固定回傳 4 顆
    seen, out = set(), []
    for c in chips + ["贏過大盤的有誰", "誰最會追高", "哪一位最值得跟"]:
        if c not in seen:
            seen.add(c); out.append(c)
    return out[:4]

_ask_chips = _gen_ask_chips()
_ask_chips_html = "".join(
    f'<button class="ask-chip" onclick="askQuick(this)">{c}</button>' for c in _ask_chips)
_fab_egs_js = json.dumps([f"「{c}？」" for c in _ask_chips], ensure_ascii=False)

html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>投顧戰績實驗室 — $100 跟他 vs $100 買大盤</title>
<script>var _cm={{}},_cmM={{}},_tbl={{}};</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--ink:#16161f;--mut:#6f7680;--line:#e7e7ea;--bgs:#f7f7f8;--up:#1a8754;--dn:#c0392b}}
html{{scroll-behavior:smooth;scroll-padding-top:64px}}
body{{font-family:'PingFang TC','Microsoft JhengHei',system-ui,sans-serif;background:#fff;color:var(--ink);line-height:1.65}}
h1,h2,.brand{{font-family:'Noto Serif TC','Songti TC',serif}}
.num{{font-variant-numeric:tabular-nums}}
img{{max-width:100%;border-radius:8px;display:block}}
.wrap{{max-width:1140px;margin:0 auto;padding:0 22px}}
/* nav */
nav{{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}}
nav .wrap{{display:flex;align-items:center;gap:26px;height:56px}}
.brand{{font-weight:900;font-size:1.02rem;white-space:nowrap;flex:none}}
nav a{{color:var(--mut);text-decoration:none;font-size:.88rem;padding:4px 2px}}
nav a:hover{{color:var(--ink)}}
nav .sp{{flex:1}}
@media(max-width:560px){{
  nav .wrap{{gap:10px;height:auto;padding-top:10px;padding-bottom:10px;flex-wrap:wrap}}
  .brand{{font-size:.88rem;order:1;flex-basis:100%}}
  nav .sp{{display:none}}
  nav .wrap>.nav-tab{{order:2;font-size:.72rem;padding:4px 9px}}
}}
/* hero：靠左 Stripe 風 */
.hero{{background:#fff;border-bottom:1px solid var(--line);padding:80px 0 56px;text-align:left}}
.hero h1{{font-size:clamp(1.8rem,4.4vw,3.1rem);font-weight:900;letter-spacing:.5px;margin-bottom:14px;color:var(--ink)}}
.hero p{{color:var(--mut);max-width:620px;margin:0 0 36px;font-size:.98rem}}
.hero-lead{{color:var(--ink)!important;font-weight:600;max-width:680px;margin:0 0 20px!important;font-size:1.02rem;line-height:1.7}}
.hero-scope{{display:flex;flex-wrap:wrap;justify-content:flex-start;gap:8px 22px;max-width:760px;margin:0 0 48px;font-size:.82rem;line-height:1.6}}
.hero-scope .hs-can{{color:#1a8754}}
.hero-scope .hs-cant{{color:var(--mut)}}
.hero-scope b{{font-weight:700}}
/* 儀表盤刊頭 */
.mast{{display:flex;align-items:stretch;flex-wrap:wrap;border-top:1px solid var(--ink);border-bottom:1px solid var(--line);margin:0 0 14px}}
.mast-hero{{flex:1.5;min-width:210px;display:flex;align-items:baseline;gap:12px;padding:20px 28px 20px 0}}
.mh-num{{font-size:clamp(3rem,7vw,4.4rem);font-weight:900;line-height:.85;color:var(--ink);font-variant-numeric:tabular-nums}}
.mh-cap{{font-size:.95rem;color:var(--ink);font-weight:600;line-height:1.4}}
.mh-cap i{{display:block;font-style:normal;font-size:.72rem;color:var(--mut);font-weight:400;margin-top:5px}}
.mast-col{{flex:1;min-width:140px;padding:20px 24px;border-left:1px solid var(--line)}}
.mc-num{{font-size:1.7rem;font-weight:800;line-height:1;color:var(--ink);font-variant-numeric:tabular-nums}}
.mc-vs{{font-size:.95rem;font-weight:400;color:var(--mut)}}
.mc-lbl{{font-size:.8rem;color:var(--ink);margin-top:8px}}
.mc-sub{{font-size:.7rem;color:var(--mut);margin-top:3px}}
.mast-foot{{font-size:.74rem;color:var(--mut);line-height:1.7;margin:0 0 4px}}
@media(max-width:680px){{.mast-hero{{flex-basis:100%;border-bottom:1px solid var(--line);padding-right:0}}.mast-col{{border-left:none;border-right:1px solid var(--line);padding-left:0;padding-right:24px}}}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:0;margin:0;text-align:left;border:1px solid var(--line);border-radius:14px;overflow:hidden}}
.tile{{background:#fff;padding:26px 28px;text-decoration:none;color:var(--ink);transition:background .15s;display:block;border-left:1px solid var(--line)}}
.tile:first-child{{border-left:none}}
.tile:hover{{background:var(--bgs)}}
.tile .tt{{font-size:.72rem;font-weight:600;letter-spacing:2px;margin-bottom:14px;display:block;color:var(--mut);text-transform:uppercase}}
.tile .duel{{font-size:1.5rem;font-weight:800}}
.tile .duel i{{font-style:normal;color:#c4c8ce;font-size:.9rem;font-weight:400;margin:0 7px}}
.tile .who{{font-size:.8rem;color:var(--mut);margin-top:8px}}
@media(max-width:780px){{.tile{{border-left:none;border-top:1px solid var(--line)}}.tile:first-child{{border-top:none}}}}
/* sections */
section{{padding:72px 0}}
section.alt{{background:#fff;border-top:1px solid var(--line)}}
.stitle{{font-size:1.45rem;font-weight:800;margin-bottom:8px}}
.ssub{{color:var(--mut);margin-bottom:28px;max-width:760px;font-size:.94rem}}
/* filter bar */
.fbar{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:24px}}
.fbar input{{flex:1;min-width:170px;padding:10px 16px;border:1px solid var(--line);border-radius:24px;font-size:.92rem;background:#fff}}
.chip{{padding:7px 16px;border:1px solid var(--line);background:#fff;border-radius:24px;font-size:.85rem;cursor:pointer;color:var(--mut)}}
.chip.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
/* cards */
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(258px,1fr));gap:14px}}
/* 名牌（牆上極簡） */
.ncard{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px 14px;cursor:pointer;transition:border-color .15s,box-shadow .15s,transform .1s}}
.ncard:hover{{border-color:#b9bdc4;box-shadow:0 4px 16px rgba(0,0,0,.06);transform:translateY(-2px)}}
.ncard-head{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}}
.ncard-name{{font-size:1.02rem;font-weight:800}}
.ncard-duel{{display:flex;align-items:baseline;justify-content:center;gap:10px;padding:2px 0 2px}}
.ncard-duel .pv{{font-size:1.5rem;font-weight:800}}
.ncard-vs{{color:#c9ccd1;font-size:.78rem}}
.ncard-spark{{height:38px;overflow:hidden;margin:2px 0 8px;opacity:.85}}
.ncard-spark .spark{{height:38px;margin:0}}
.ncard-verdict{{font-size:.76rem;color:#4a5260;font-weight:600;line-height:1.45;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
/* 浮層 */
.modal{{display:none;position:fixed;inset:0;z-index:200;background:rgba(20,20,28,.55);
  backdrop-filter:blur(3px);padding:40px 16px;overflow-y:auto}}
.modal.on{{display:block}}
.modal-box{{background:#fff;max-width:520px;margin:0 auto;border-radius:16px;padding:24px 26px 22px;
  position:relative;box-shadow:0 20px 60px rgba(0,0,0,.3)}}
.modal-x{{position:absolute;top:14px;right:16px;border:none;background:none;font-size:1.1rem;
  cursor:pointer;color:var(--mut);line-height:1}}
body.modal-open{{overflow:hidden}}
.pcard{{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;transition:border-color .15s}}
.pcard:hover{{border-color:#b9bdc4}}
.pbody{{padding:20px 22px 18px}}
.phead{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}}
.pname{{font-size:1.12rem;font-weight:800}}
.psample{{font-size:.76rem;color:var(--mut);margin-top:2px}}
.psample-scope{{font-size:.72rem;margin-top:5px;padding:4px 8px;background:#f6f7f9;border-radius:6px;display:inline-block}}
.ptag{{font-size:.7rem;font-weight:600;padding:3px 10px;border-radius:20px;white-space:nowrap;color:var(--mut);border:1px solid var(--line);letter-spacing:1px}}
.pduel{{display:flex;align-items:center;justify-content:center;gap:18px;padding:6px 0 10px}}
.pside{{text-align:center}}
.pv{{font-size:1.7rem;font-weight:800;line-height:1.1}}
.pv.pos{{color:var(--up)}}.pv.neg{{color:var(--dn)}}.pv.flat{{color:#5b6470}}.pv.mkt{{color:#9aa0a8}}
.pl{{font-size:.7rem;color:var(--mut);margin-top:3px}}
.pvs{{color:#c9ccd1;font-size:.85rem}}
.spark{{width:100%;height:64px;margin:2px 0 10px}}
.pverdict{{font-size:.8rem;color:#4a5260;font-weight:600;padding:9px 12px;background:var(--bgs);border-radius:9px}}
.pdetail{{margin-top:12px;font-size:.82rem}}
.pdetail>summary{{cursor:pointer;color:var(--mut);font-size:.8rem;user-select:none}}
.pdetail[open]>summary{{margin-bottom:10px}}
details.sub{{margin-top:10px}}
details.sub>summary{{cursor:pointer;font-size:.78rem;color:var(--mut)}}
details.sub img{{margin-top:8px}}
.note{{font-size:.78rem;color:var(--mut);background:var(--bgs);border-radius:8px;padding:9px 12px;line-height:1.6;margin-bottom:8px}}
.finding{{font-size:.8rem;background:var(--bgs);border-left:2px solid var(--ink);border-radius:0 8px 8px 0;padding:9px 12px;color:#333;margin-top:8px;line-height:1.6}}
.mrow{{display:flex;justify-content:space-around;margin:12px 0 4px}}
.m{{text-align:center}}.mv{{font-size:1rem;font-weight:700}}.ml{{font-size:.7rem;color:var(--mut)}}
.bw{{display:flex;justify-content:space-between;margin-top:10px;font-size:.78rem}}
.best{{color:#1a8754;font-weight:600}}.worst{{color:#c0392b;font-weight:600}}
.ci-wrap{{margin:4px 0 10px}}
.ci-row{{display:flex;justify-content:space-between;font-size:.74rem;color:var(--mut);margin-bottom:5px;gap:8px;flex-wrap:wrap}}
.ci-track{{position:relative;height:8px;background:#f0f1f4;border-radius:4px}}
.ci-zero{{position:absolute;left:50%;top:-3px;width:1.5px;height:14px;background:#ccc;z-index:1}}
.ci-range{{position:absolute;top:0;height:8px;border-radius:4px}}
.ci-dot{{position:absolute;top:50%;transform:translate(-50%,-50%);width:8px;height:8px;border-radius:50%;z-index:2}}
.ttbl{{margin:4px 0}}
.trow{{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid #f3f4f7;font-size:.78rem;align-items:baseline}}
.trow.th{{color:var(--mut);font-size:.72rem;border-bottom:1px solid var(--line)}}
.tname{{flex:1;font-weight:600}}.tname i{{color:#9aa3af;font-weight:400;font-style:normal}}
.trow span:not(.tname){{min-width:96px;text-align:right}}
.dots{{line-height:1.5;margin-bottom:8px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin:1.5px}}
/* 比例條（命中/未中/待定，全卡共用） */
.hitbar{{display:flex;height:20px;border-radius:6px;overflow:hidden;margin:10px 0 6px;background:#eef0f3}}
.hitbar>div{{height:100%}}
.hb-g{{background:#1a8754}}.hb-r{{background:#c0392b}}.hb-y{{background:#dfe2e7}}
.hb-leg{{display:flex;gap:16px;flex-wrap:wrap;font-size:.72rem;color:var(--mut);margin-bottom:10px}}
.prow{{display:flex;gap:8px;align-items:baseline;padding:5px 0;border-bottom:1px solid #f3f4f7;font-size:.76rem}}
.ptag2{{flex-shrink:0;background:#fff0f0;color:#c0392b;border-radius:4px;padding:1px 6px;font-size:.7rem}}
.pdt{{color:#9aa3af;flex-shrink:0}}
.pq{{flex:1;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.crow{{display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:.74rem;padding:7px 0;border-bottom:1px solid #f3f4f7;color:#777}}
/* tabs / charts */
.tabs{{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap}}
.tab{{padding:9px 18px;border:1px solid var(--line);background:#fff;border-radius:10px;font-size:.88rem;cursor:pointer;color:var(--mut)}}
.tab.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.pane{{display:none;background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px}}
.pane.on{{display:block}}
.cap{{margin-top:14px;font-size:.88rem;color:#555;line-height:1.7;border-left:2px solid var(--ink);padding-left:13px}}
.stbl{{width:100%;border-collapse:collapse;font-size:.9rem;margin-top:16px}}
.stbl th{{text-align:left;padding:10px 12px;background:var(--bgs);color:var(--mut);font-size:.78rem}}
.stbl td{{padding:10px 12px;border-bottom:1px solid #f3f4f7}}
.stbl tr.hl{{background:var(--bgs);font-weight:600}}
/* 自選淨值實驗台 */
.cmp-bar{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}}
.cmp-sp{{flex:1}}
/* ＋加入分析師 下拉 */
.cmp-add-wrap{{position:relative}}
.cmp-add-btn{{padding:7px 14px;border:1px solid var(--line);border-radius:9px;background:#fff;font-size:.82rem;cursor:pointer;color:var(--ink);font-family:inherit;transition:background .12s}}
.cmp-add-btn:hover{{background:var(--bgs)}}
.cmp-add-btn.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.cmp-add-panel{{display:none;position:absolute;top:calc(100% + 6px);right:0;z-index:60;background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.14);padding:8px;min-width:250px;max-height:320px;overflow-y:auto}}
.cmp-add-panel.on{{display:block}}
.cmp-add-seg{{display:flex;width:100%;margin-bottom:6px}}
.cmp-add-seg button{{flex:1;padding:5px 4px;font-size:.74rem;white-space:nowrap}}
.cmp-opt{{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:7px;cursor:pointer;font-size:.84rem;color:var(--ink)}}
.cmp-opt:hover{{background:var(--bgs)}}
.cmp-opt.on{{font-weight:700}}
.cmp-opt .dotc{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}
.cmp-opt-nm{{flex:1}}
.cmp-opt-ck{{color:var(--up);font-weight:700}}
#cmp-chart{{width:100%;height:auto;display:block;background:#fff;border:1px solid var(--line);border-radius:12px}}
.cmp-legend{{display:grid;grid-template-columns:auto auto auto auto;gap:8px 18px;margin-top:14px;font-size:.8rem;width:fit-content;max-width:100%;align-items:center}}
.cmp-lg-x{{border:none;background:none;color:#c9ccd1;cursor:pointer;font-size:.78rem;padding:2px 4px;line-height:1}}
.cmp-lg-x:hover{{color:var(--dn)}}
.cmp-tabs{{display:flex;gap:6px;margin:0}}
.cmp-tab{{padding:5px 15px;border-radius:20px;border:1.5px solid var(--line);background:transparent;font-size:.8rem;cursor:pointer;color:var(--mut);font-weight:600}}
.cmp-tab.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.cmp-lg-name{{display:flex;align-items:center;gap:7px;color:var(--ink)}}
.cmp-lg-name .dotc{{width:10px;height:10px;border-radius:2px;flex-shrink:0}}
.cmp-lg-v{{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}}
.cmp-lg-a{{text-align:right;font-size:.76rem;font-variant-numeric:tabular-nums;color:var(--mut)}}
/* 報酬拆解：一人一張小圖 */
.facu-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:6px}}
.facu{{border:1px solid var(--line);border-radius:10px;padding:13px 15px}}
.facu-h{{display:flex;justify-content:space-between;align-items:baseline;font-weight:700;font-size:.88rem;margin-bottom:11px}}
.facu-h .tot{{font-variant-numeric:tabular-nums}}
.facu-row{{display:flex;align-items:center;gap:9px;margin:6px 0;font-size:.73rem}}
.facu-lbl{{width:52px;flex-shrink:0;color:var(--mut)}}
.facu-track{{flex:1;height:15px;position:relative;background:#f6f6f8;border-radius:3px}}
.facu-zero{{position:absolute;left:50%;top:-3px;width:1px;height:21px;background:#ccd}}
.facu-seg{{position:absolute;top:0;height:100%;border-radius:3px}}
.facu-val{{width:50px;flex-shrink:0;text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
/* method */
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:48px}}
.mbox{{background:none;border:none;border-top:1px solid var(--ink);border-radius:0;padding:18px 0 0}}
.mbox h3{{font-size:.82rem;font-weight:700;margin-bottom:14px;letter-spacing:.5px}}
.mbox li{{padding:8px 0 8px 16px;position:relative;font-size:.86rem;color:#555;border-bottom:1px solid var(--line);list-style:none}}
.mbox li:before{{content:"·";position:absolute;left:2px;color:#9aa3af;font-weight:900}}
.disc{{background:none;border:none;border-top:1px solid var(--line);border-radius:0;padding:18px 0 0;margin-top:32px;font-size:.82rem;color:#55595f;line-height:1.7}}
/* period picker */
.ppick{{display:flex;gap:5px;margin:0;flex-wrap:wrap}}
.ppick button{{padding:3px 10px;border:1px solid var(--line);background:#fff;border-radius:16px;font-size:.75rem;cursor:pointer;color:var(--mut)}}
.ppick button.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
/* 統一控制條：天數＋方向 */
.ctrlrow{{display:flex;align-items:center;gap:10px;margin:6px 0;flex-wrap:wrap}}
.ctrlrow .mtog{{margin:0;justify-content:flex-start}}
.ctrll{{font-size:.66rem;font-weight:600;letter-spacing:1px;color:var(--mut);min-width:48px;text-transform:uppercase}}
.ctrlpanel{{background:var(--bgs);border:1px solid var(--line);border-radius:10px;padding:7px 13px;margin:2px 0 14px}}
.ctrlpanel .ctrlrow:first-child{{margin-top:0}}
.ctrlpanel .ctrlrow:last-child{{margin-bottom:0}}
.psec-hdr2{{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:4px 0 10px}}
.psec-hdr2 .psec-hdr{{margin:0}}
.psec-base{{display:flex;align-items:center;gap:8px}}
.psec-base .mtog{{margin:0}}
.psec-base .mtog button{{font-size:.7rem;padding:2px 10px}}
.psec-base .ctrll{{min-width:0}}
.pspark{{margin:4px 0 2px}}
/* ── 三層卡片 ── */
/* ── 第三部分：體檢表 ── */
.hc-wrap{{margin:0}}
.hc-row{{display:grid;grid-template-columns:80px 1fr 82px;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)}}
.hc-row:last-child{{border-bottom:none}}
.hc-label{{font-size:.68rem;font-weight:700;color:var(--ink);letter-spacing:.3px}}
.hc-note{{font-size:.63rem;color:var(--mut);margin-top:2px}}
.hc-big{{font-size:.95rem;font-weight:800;line-height:1.2}}
.hc-det{{font-size:.72rem;margin-top:8px}}
.hc-det summary{{cursor:pointer;color:var(--mut);font-size:.68rem;padding:4px 0;list-style:none}}
.hc-det summary::-webkit-details-marker{{display:none}}
.hc-trades{{margin-top:6px}}
.hc-trade{{display:grid;grid-template-columns:46px 1fr 48px;gap:4px;padding:3px 0;border-bottom:1px solid #f0f0f0;font-size:.67rem}}
.hc-trade:last-child{{border-bottom:none}}
.hc-trade .htk{{font-weight:700}}
.hc-trade .hdt{{color:var(--mut)}}
.hc-trade .hex{{font-weight:700;text-align:right}}
.hc-sep{{height:1px;border:none;border-top:1px dashed var(--line);margin:4px 0}}
.layer-sep{{height:1px;background:var(--line);margin:14px -22px 14px}}
.l1-risk{{font-size:.8rem;color:var(--mut);margin:8px 0 2px;text-align:center}}
.psec-hdr{{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-size:.82rem;font-weight:700;color:var(--ink);margin:4px 0 10px;letter-spacing:.5px}}
.psec-hdr .psec-q{{font-weight:400;color:var(--mut);font-size:.76rem;margin-left:4px}}
.psec-sub{{font-size:.74rem;color:var(--mut);margin:-6px 0 10px}}
.psec-div{{height:6px;background:repeating-linear-gradient(90deg,var(--line),var(--line) 4px,transparent 4px,transparent 8px);margin:18px -22px 16px}}
.lsect3{{margin-bottom:10px}}
.lsect3-hdr{{font-size:.68rem;font-weight:600;letter-spacing:1.5px;color:var(--mut);text-transform:uppercase;margin-bottom:10px}}
.pstats{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}}
.pstat{{text-align:center;background:var(--bgs);border-radius:8px;padding:8px 4px 7px}}
.pstat-v{{font-size:.92rem;font-weight:700;line-height:1.2}}
.pstat-l{{font-size:.65rem;color:var(--mut);margin-top:3px}}
/* 八欄預測紀錄表 */
.rtbl{{width:100%;border-collapse:collapse;font-size:.72rem;margin:6px 0}}
.rtbl th{{position:sticky;top:0;background:var(--bgs);color:var(--mut);font-weight:600;padding:6px 5px;text-align:right;font-size:.68rem;white-space:nowrap}}
.rtbl th:nth-child(-n+4){{text-align:left}}
.rtbl td{{padding:5px;border-bottom:1px solid #f3f4f7;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.rtbl td:nth-child(-n+4){{text-align:left}}
.rtbl tr:nth-child(even) td{{background:#fafafb}}
.rtbl .rsum{{max-width:130px;overflow:hidden;text-overflow:ellipsis}}
.rtbl tr.pend td{{color:#aab0b8;background:#fafafa}}
.rtbl-wrap{{max-height:340px;overflow-y:auto;border:1px solid var(--line);border-radius:8px}}
.rnote{{font-size:.7rem;color:var(--mut);margin:4px 0 6px}}
/* 看多/雙向/看空 切換 */
.mtog{{display:flex;gap:5px;margin:0 0 6px;justify-content:center}}
.mtog button{{padding:3px 12px;border:1px solid var(--line);background:#fff;border-radius:16px;font-size:.74rem;cursor:pointer;color:var(--mut)}}
.mtog button.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.mpane{{display:none}}.mpane.on{{display:block}}
.mhint{{font-size:.68rem;color:#b06a00;background:#fff7e6;border-radius:6px;padding:3px 8px;margin:2px 0 8px;text-align:center}}
/* ── 整體統計 ── */
.ov-section{{padding:56px 0 48px;border-bottom:1px solid var(--line)}}
.ov-section.alt{{background:var(--bgs)}}
.ov-grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}}
.ov-card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 22px}}
.ov-card h3{{font-size:.78rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mut);margin-bottom:14px}}
/* 儀表板卡牆 */
.dash-wall{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.dash-wall .dash-wide{{grid-column:1/-1}}
.gbars{{display:flex;flex-direction:column;gap:10px;margin:2px 0 12px}}
.gbar-row{{display:grid;grid-template-columns:96px 1fr 60px;align-items:center;gap:10px}}
.gbar-name{{font-size:.76rem;font-weight:600;text-align:right;white-space:nowrap}}
.gbar-name i{{display:block;font-style:normal;font-size:.6rem;font-weight:400;color:var(--mut)}}
.gbar-track{{height:16px;background:#f0f1f4;border-radius:5px;overflow:hidden}}
.gbar-fill{{height:100%;border-radius:5px;transition:width .3s}}
.gbar-val{{font-size:.8rem;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}}
/* α 置中發散橫條 */
.abars{{display:flex;flex-direction:column;gap:7px;margin:4px 0 12px}}
.abar-row{{display:grid;grid-template-columns:84px 1fr 56px;align-items:center;gap:10px}}
.abar-name{{font-size:.74rem;color:var(--mut);text-align:right;white-space:nowrap}}
.abar-track{{position:relative;height:15px;background:#f5f6f8;border-radius:4px}}
.abar-zero{{position:absolute;left:50%;top:-2px;bottom:-2px;width:1.5px;background:#c9ccd1;transform:translateX(-50%)}}
.abar-fill{{position:absolute;top:0;height:100%;transition:width .3s}}
.abar-val{{font-size:.76rem;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}}
/* 兩層式探索 */
.layer-label{{display:flex;align-items:center;gap:10px;font-size:.95rem;font-weight:700;color:var(--ink);margin:34px 0 14px}}
.layer-label .ln{{font-size:.62rem;font-weight:700;letter-spacing:1px;color:#fff;background:var(--ink);border-radius:5px;padding:3px 8px}}
.type-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.type-card{{text-align:left;background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px;cursor:pointer;transition:border-color .15s,box-shadow .15s;font-family:inherit}}
.type-card:hover{{border-color:#b9bdc4}}
.type-card.on{{border-color:var(--ink);box-shadow:0 0 0 1.5px var(--ink)}}
.tc-top{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}}
.tc-name{{font-size:1rem;font-weight:800}}
.tc-n{{font-size:.68rem;color:var(--mut)}}
.tc-duel{{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}}
.tc-duel.big{{justify-content:center;gap:12px;margin:10px 0 6px}}
.tc-v{{font-size:1.5rem;font-weight:800;font-variant-numeric:tabular-nums}}
.tc-duel.big .tc-v{{font-size:2rem}}
.tc-vs{{font-size:.7rem;color:var(--mut)}}
.tc-v2{{font-size:1.2rem;font-weight:700;color:#9aa0a8;font-variant-numeric:tabular-nums}}
.tc-concl{{font-size:.78rem;color:#4a5260;line-height:1.5;margin-bottom:10px}}
.ov-kv{{font-size:.82rem;color:#4a5260;text-align:center;margin-top:4px}}
.type-tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.ttab{{padding:7px 16px;border:1px solid var(--line);border-radius:20px;background:#fff;font-size:.84rem;cursor:pointer;color:var(--mut);font-weight:600}}
.ttab.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
.fdr-tbl{{width:100%;border-collapse:collapse;font-size:.8rem}}
.fdr-tbl th{{color:var(--mut);font-weight:600;font-size:.7rem;padding:4px 8px;text-align:right;border-bottom:2px solid var(--line)}}
.fdr-tbl th:first-child{{text-align:left}}
.fdr-tbl td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums}}
.fdr-tbl td:first-child{{text-align:left;font-weight:600}}
.fdr-tbl .fdr-ok{{color:#1a8754;font-weight:700}}
.fdr-tbl .fdr-no{{color:#c0392b}}
.verdict-tbl{{width:100%;border-collapse:collapse;font-size:.78rem}}
.verdict-tbl th{{color:var(--mut);font-weight:600;font-size:.68rem;padding:4px 6px;text-align:left;border-bottom:2px solid var(--line)}}
.verdict-tbl td{{padding:7px 6px;border-bottom:1px solid #f0f0f3;vertical-align:middle}}
.verdict-badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.65rem;font-weight:700}}
.vb-fdr{{background:#d1fae5;color:#065f46}}
.vb-raw{{background:#fef3c7;color:#92400e}}
.vb-raw-neg{{background:#fde2e1;color:#a12b23}}
.vb-none{{background:#f3f4f6;color:#6b7280}}
.runup-bar-wrap{{margin:6px 0;display:flex;align-items:center;gap:8px;font-size:.75rem}}
.runup-bar{{flex:1;height:8px;background:#e5e7eb;border-radius:4px;overflow:hidden}}
.runup-bar-fill{{height:100%;border-radius:4px;background:#2563eb}}
.runup-bar-fill.gooaye{{background:#9ca3af}}
.alpha-chart{{position:relative;height:180px;margin-top:10px}}
.sens-tbl{{width:100%;border-collapse:collapse;font-size:.78rem}}
.sens-tbl th{{color:var(--mut);font-weight:600;font-size:.68rem;padding:4px 8px;text-align:right;border-bottom:2px solid var(--line)}}
.sens-tbl th:first-child{{text-align:left}}
.sens-tbl td{{padding:7px 8px;border-bottom:1px solid #f0f0f3;text-align:right;font-variant-numeric:tabular-nums}}
.sens-tbl td:first-child{{text-align:left}}
.ov-note{{font-size:.72rem;color:var(--mut);margin-top:10px;line-height:1.6;border-left:3px solid var(--line);padding-left:10px}}
.finding-box{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}}
.finding{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 18px}}
.finding-num{{font-size:1.6rem;font-weight:900;line-height:1;margin-bottom:4px}}
.finding-lbl{{font-size:.72rem;color:var(--mut);line-height:1.4}}
@media(max-width:700px){{.ov-grid{{grid-template-columns:1fr}}.finding-box{{grid-template-columns:1fr 1fr}}}}
footer{{padding:40px 0 96px;background:#fff;border-top:1px solid var(--line);color:var(--mut)}}
.foot-scope{{display:flex;flex-wrap:wrap;gap:6px 28px;font-size:.84rem;margin-bottom:18px}}
.foot-scope b{{color:var(--ink)}}
.foot-meth{{font-size:.74rem;line-height:1.7;max-width:760px;margin-bottom:8px}}
.foot-meth b{{color:var(--ink)}}
.foot-disc{{font-size:.72rem;line-height:1.7;max-width:760px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line);color:#8a9099}}
.foot-disc b{{color:var(--mut)}}
@media(max-width:600px){{nav a.opt{{display:none}}}}
/* ── 兩頁切換 ── */
.page{{display:none}}.page.on{{display:block}}
.nav-tab{{padding:4px 14px;border:1px solid var(--line);border-radius:16px;background:#fff;font-size:.82rem;cursor:pointer;color:var(--mut);font-weight:500}}
.nav-tab.on{{background:var(--ink);color:#fff;border-color:var(--ink)}}
/* ── 個人頁：sidebar + right pane ── */
.personal-layout{{display:grid;grid-template-columns:248px 1fr 340px;gap:16px;height:calc(100vh - 56px);padding:16px;background:var(--bgs);overflow:hidden;box-sizing:border-box}}
.sidebar{{border:1px solid var(--line);border-radius:12px;overflow-y:auto;background:#fff;padding:10px 0}}
.sb-search{{display:block;width:calc(100% - 20px);margin:0 10px 8px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;font-size:.78rem;background:#fff;outline:none}}
.sb-item{{display:grid;grid-template-columns:1fr auto;grid-template-rows:auto auto;gap:1px 6px;width:100%;padding:10px 14px;border:none;background:none;cursor:pointer;text-align:left;border-bottom:1px solid #f0f0f0}}
.sb-item:hover{{background:#f0f0f3}}
.sb-item.on{{background:#16161f;color:#fff}}
.sb-item.on .sb-tag,.sb-item.on .sb-val{{color:#a0a0a8}}
.sb-name{{font-size:.82rem;font-weight:700;grid-column:1;grid-row:1}}
.sb-tag{{font-size:.62rem;color:var(--mut);grid-column:1;grid-row:2}}
.sb-val{{font-size:.78rem;font-weight:700;grid-column:2;grid-row:1/3;align-self:center}}
.sb-val.pos{{color:#1a8754}}.sb-val.neg{{color:#c0392b}}.sb-val.flat{{color:var(--mut)}}
.right-pane{{overflow-y:auto;padding:0;background:transparent}}
#rp-content{{padding:0 2px 24px;max-width:860px}}
#rp-content .modal-x{{display:none}}
/* ── 個人頁第三欄：分析師專屬 AI 對話 ── */
.chat-pane{{border:1px solid var(--line);border-radius:12px;background:#fff;display:flex;flex-direction:column;overflow:hidden;padding:14px 14px 12px}}
.chat-title{{margin:0 0 10px;font-size:.86rem;font-weight:700;color:var(--ink)}}
.chat-messages{{flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:10px;margin-bottom:10px}}
.chat-messages .ask-empty{{font-size:.78rem;color:var(--mut);text-align:center;padding:24px 8px;line-height:1.6}}
.chat-messages .ask-card{{font-size:.82rem;padding:14px 16px}}
.chat-input-box{{display:flex;gap:8px}}
.chat-input-box input{{flex:1;min-width:0;padding:8px 12px;border:1px solid var(--line);border-radius:20px;font-size:.82rem;outline:none}}
.chat-input-box .ask-btn{{padding:8px 16px;border-radius:20px;white-space:nowrap}}
/* ── 第二頁：模塊化卡片（對齊第一頁 ov-card 風格）── */
.pmod{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-bottom:16px}}
.pmod-head{{padding-bottom:16px}}
#rp-content .pmod .phead{{margin-bottom:0}}
#rp-content .layer-sep,#rp-content .psec-div{{display:none}}
.pmod .layer-sep{{display:none}}
/* 控制條直接坐在卡片裡，不要再套一層灰色內框（box-in-box）*/
#rp-content .ctrlpanel{{background:transparent;border:none;border-radius:0;padding:0;margin:2px 0 0}}
#rp-content .pmod-head{{padding-bottom:18px}}
.sb-filter{{display:flex;gap:6px;padding:0 10px 8px;flex-wrap:wrap}}
.sb-filter .chip{{font-size:.66rem;padding:2px 9px}}
/* modal-store 裡的 modal 不作 overlay 顯示 */
#modal-store .modal:not(.on){{display:none!important}}
#rp-content .modal-box{{position:static;border-radius:0;box-shadow:none;max-height:none;width:auto;max-width:100%;padding:0}}
@media(max-width:1200px){{
  /* 第三欄掉到中欄下方整排堆疊，改成整頁可捲不再固定視窗高 */
  .personal-layout{{grid-template-columns:248px 1fr;height:auto;overflow:visible}}
  .sidebar,.right-pane{{max-height:calc(100vh - 120px)}}
  .chat-pane{{grid-column:1/-1;height:420px}}
}}
@media(max-width:700px){{
  .personal-layout{{grid-template-columns:148px 1fr;gap:10px;padding:10px}}
  #rp-content{{padding:0 2px 16px}}
  .pmod{{padding:16px 14px}}
}}
@media(max-width:560px){{
  .personal-layout{{display:block;height:auto;overflow:visible;padding:10px}}
  .sidebar{{width:100%;max-height:190px;margin-bottom:12px}}
  .right-pane{{overflow-y:visible;height:auto}}
  #rp-content{{max-width:100%}}
  .chat-pane{{width:100%;height:360px;margin-top:12px}}
}}
/* ── 排行榜表格 ── */
.ov-filter-row{{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:20px 0 12px}}
.ov-filter-group{{display:flex;align-items:center;gap:7px}}
.ov-filter-lbl{{font-size:.7rem;font-weight:700;letter-spacing:1px;color:var(--mut);text-transform:uppercase}}
.ov-filter-group select{{padding:6px 26px 6px 10px;border:1px solid var(--line);border-radius:20px;font-size:.84rem;background:#fff;cursor:pointer;color:var(--ink);-webkit-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='7'%3E%3Cpath d='M1 1l5 5 5-5' fill='none' stroke='%236f7680' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 9px center}}
.ov-tbl-wrap{{overflow-x:auto}}
.ov-tbl{{width:100%;border-collapse:collapse;font-size:.84rem}}
.ov-tbl thead th{{background:none;padding:8px 12px;text-align:left;font-size:.7rem;font-weight:400;letter-spacing:.5px;color:var(--mut);white-space:nowrap;border-bottom:1px solid var(--line)}}
.ov-tbl thead .ov-th-val,.ov-tbl thead .ov-th-val2,.ov-tbl thead .ov-th-raw,.ov-tbl thead .ov-th-detail,.ov-tbl thead .ov-th-fdr{{text-align:right}}
.ov-td-val2{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.ov-th-val2,.ov-th-raw{{white-space:nowrap}}
.ov-td-raw{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.ov-raw-num{{font-size:.82rem;opacity:.6}}   /* 淡化：情境參考，非評分 */
.ov-raw-mkt{{display:block;font-size:.62rem;color:var(--mut);opacity:.75;margin-top:1px}}
.ov-raw-flex{{display:flex;align-items:center;justify-content:flex-end;gap:6px}}   /* 左：數字/大盤疊；右：條 */
.ov-raw-stack{{display:flex;flex-direction:column;align-items:flex-end;line-height:1.3}}
.ov-mkt-tip{{cursor:help}}
.ov-sortbar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:4px 0 16px}}
.ov-sortbar-lbl{{font-size:.7rem;font-weight:700;letter-spacing:1px;color:var(--mut);text-transform:uppercase}}
.ov-sortbar .mtog button{{font-size:.8rem;padding:5px 13px}}
.ov-row td{{padding:11px 12px;border-bottom:1px solid #f3f4f7;vertical-align:middle}}
.ov-row:last-child td{{border-bottom:none}}
.ov-row:hover td{{background:var(--bgs)}}
.ov-row-dim td{{color:#b0b5bc}}
.ov-td-name{{font-weight:700;font-size:.86rem;white-space:nowrap}}
.ov-td-track{{display:block;font-weight:400;font-size:.68rem;color:var(--mut);margin-top:2px}}
.ov-td-type{{white-space:nowrap}}
.ov-td-val{{text-align:right;white-space:nowrap}}
.ov-td-detail{{text-align:right;font-size:.74rem;color:var(--mut);white-space:nowrap}}
.ov-td-fdr{{text-align:right;white-space:nowrap}}
.ov-val-num{{font-weight:700;font-variant-numeric:tabular-nums;margin-right:5px}}
.ov-na{{color:#c9ccd1}}
/* 類型標籤 */
.ov-type-chip{{display:inline-block;font-size:.62rem;font-weight:700;padding:2px 8px;border-radius:10px;letter-spacing:.5px}}
.ov-tc-call{{background:#eef2ff;color:#3730a3}}
.ov-tc-macro{{background:#d1fae5;color:#065f46}}
.ov-tc-myst{{background:#fef3c7;color:#92400e}}
/* cell 迷你橫條 */
.mc-track{{position:relative;display:inline-block;width:60px;height:10px;background:#f0f1f4;border-radius:3px;vertical-align:middle;margin-left:4px}}
.mc-zero{{position:absolute;left:50%;top:-2px;bottom:-2px;width:1.5px;background:#d0d3d8;transform:translateX(-50%)}}
.mc-fill{{position:absolute;top:0;height:100%}}
.mc-track-s{{display:inline-block;width:60px;height:10px;background:#f0f1f4;border-radius:3px;vertical-align:middle;margin-left:4px;overflow:hidden}}
.mc-fill-s{{height:100%;border-radius:3px}}
.ov-tbl-note{{font-size:.72rem;color:var(--mut);margin-top:10px;line-height:1.6}}
/* ══ Stripe 風統一 token ══ */
.sec-h{{display:flex;align-items:center;gap:9px;margin-bottom:22px}}
.sec-h .stitle{{margin:0;font-weight:700}}
/* ⓘ 規則 tooltip */
.info{{position:relative;display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;border:1px solid var(--line);border-radius:50%;font-size:.66rem;color:var(--mut);cursor:help;font-style:normal;flex-shrink:0;line-height:1;font-family:Georgia,serif;vertical-align:middle}}
.info:hover{{border-color:var(--ink);color:var(--ink)}}
.info::after{{content:attr(data-tip);position:absolute;left:50%;top:calc(100% + 9px);transform:translateX(-50%);background:var(--ink);color:#fff;font-size:.74rem;font-weight:400;line-height:1.55;letter-spacing:0;padding:9px 12px;border-radius:9px;width:240px;text-align:left;opacity:0;visibility:hidden;transition:opacity .12s;z-index:80;box-shadow:0 8px 24px rgba(0,0,0,.18)}}
.info::before{{content:"";position:absolute;left:50%;top:calc(100% + 4px);transform:translateX(-50%) rotate(45deg);width:9px;height:9px;background:var(--ink);opacity:0;visibility:hidden;transition:opacity .12s;z-index:81}}
.info::after,.info::before{{display:none!important}}  /* CSS 泡泡停用：改走 JS 浮動提示（會翻邊、不被裁切） */
.info{{cursor:help}}
.info.tr::after{{left:auto;right:-2px;transform:none}}
.info.tr::before{{left:auto;right:5px;transform:rotate(45deg)}}
/* 往上開（頁尾用，避免被視窗底切掉）*/
.info.up::after{{top:auto;bottom:calc(100% + 9px)}}
.info.up::before{{top:auto;bottom:calc(100% + 4px)}}
/* 頁尾方法列：一行放幾個 ⓘ */
.foot-scope-line{{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;font-size:.8rem;color:var(--mut)}}
.foot-scope-line .info{{margin-left:3px}}
/* segmented 膠囊 */
.ov-filter-row{{align-items:flex-end}}
.seg-wrap{{display:flex;flex-direction:column;gap:6px}}
.seg-lbl{{font-size:.66rem;font-weight:700;letter-spacing:1px;color:var(--mut);text-transform:uppercase}}
.seg{{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;flex-wrap:wrap}}
.seg button{{padding:7px 14px;border:none;background:#fff;font-size:.82rem;cursor:pointer;color:var(--mut);border-left:1px solid var(--line);font-family:inherit;transition:background .12s}}
.seg button:first-child{{border-left:none}}
.seg button:hover:not(.on){{background:var(--bgs)}}
.seg button.on{{background:var(--ink);color:#fff}}
/* ── AI 問答 ── */
.ask-section{{padding:72px 0;border-top:1px solid var(--line)}}
.ask-box{{max-width:680px;margin:0 auto}}
.ask-bar{{display:flex;gap:10px;margin-bottom:16px}}
.ask-bar input{{flex:1;padding:12px 18px;border:1px solid var(--line);border-radius:24px;font-size:.95rem;background:#fff;outline:none;transition:border-color .2s}}
.ask-bar input:focus{{border-color:var(--ink)}}
.ask-btn{{padding:10px 22px;border:none;background:var(--ink);color:#fff;border-radius:24px;font-size:.88rem;cursor:pointer;font-weight:600;white-space:nowrap;transition:opacity .15s}}
.ask-btn:hover{{opacity:.85}}
.ask-btn:disabled{{opacity:.5;cursor:not-allowed}}
.ask-chips{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}}
.ask-chip{{padding:7px 14px;border:1px solid var(--line);background:#fff;border-radius:24px;font-size:.82rem;cursor:pointer;color:var(--mut);transition:background .12s,border-color .12s}}
.ask-chip:hover{{background:var(--bgs);border-color:#c4c8ce}}
.ask-result{{min-height:60px}}
/* 對話串：逐則堆疊、可一來一回 */
.ask-log{{display:flex;flex-direction:column;gap:14px}}
.ask-turn{{display:flex}}
.ask-turn.user{{justify-content:flex-end}}
.ask-turn.bot{{justify-content:flex-start}}
.ask-q{{background:var(--ink);color:#fff;border-radius:16px 16px 4px 16px;padding:10px 16px;font-size:.9rem;max-width:80%;line-height:1.55}}
.ask-turn.bot .ask-card,.ask-turn.bot .ask-loading,.ask-turn.bot .ask-error{{max-width:88%;margin:0}}
.ask-card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px 24px;line-height:1.7;font-size:.9rem;color:var(--ink)}}
.ask-card h3{{font-size:.95rem;font-weight:700;margin:14px 0 8px}}
.ask-card ul,.ask-card ol{{padding-left:18px;margin:6px 0}}
.ask-card li{{margin:4px 0}}
.ask-card strong{{font-weight:700}}
.ask-card code{{background:var(--bgs);padding:1px 5px;border-radius:4px;font-size:.84rem}}
.ask-card blockquote{{border-left:3px solid var(--line);padding-left:12px;color:var(--mut);margin:8px 0}}
.ask-card table{{width:100%;border-collapse:collapse;font-size:.82rem;margin:10px 0}}
.ask-card th{{text-align:left;padding:6px 8px;background:var(--bgs);font-size:.74rem;color:var(--mut);font-weight:600}}
.ask-card td{{padding:6px 8px;border-bottom:1px solid #f3f4f7}}
.ask-empty{{text-align:center;color:var(--mut);font-size:.88rem;padding:32px 0}}
.ask-empty .ask-icon{{font-size:2rem;margin-bottom:8px;opacity:.5}}
.ask-loading{{padding:14px 4px;color:var(--mut);font-size:.9rem}}
.ask-dots span{{display:inline-block;width:6px;height:6px;background:var(--mut);border-radius:50%;margin:0 2px;animation:askBounce .6s ease-in-out infinite}}
.ask-dots span:nth-child(2){{animation-delay:.1s}}
.ask-dots span:nth-child(3){{animation-delay:.2s}}
@keyframes askBounce{{0%,80%,100%{{transform:translateY(0)}}40%{{transform:translateY(-8px)}}}}
.ask-error{{color:var(--dn);font-size:.86rem;padding:14px 4px}}
.ask-offline{{text-align:center;color:var(--mut);font-size:.84rem;padding:24px 0;background:var(--bgs);border-radius:10px}}
/* ── v2 單頁版 ── */
.verdict-line{{font-size:1.08rem;max-width:640px;margin:14px 0 26px;color:var(--ink)}}
.verdict-line b{{border-bottom:3px solid var(--dn)}}
.hero-duel{{display:flex;align-items:center;gap:26px;margin:6px 0 20px}}
.hd-num{{font-size:2.6rem;font-weight:800;letter-spacing:-.02em;color:var(--up)}}
.hd-num.hd-mkt{{color:var(--mut)}}
.hd-vs{{color:var(--mut);font-size:.95rem}}
.hd-lbl{{font-size:.82rem;color:var(--mut)}}
.cmp-howto{{margin-left:auto;font-size:.82rem;color:var(--mut);font-weight:400;display:inline-flex;align-items:center;gap:4px}}
.cmp-howto:empty{{display:none}}
.ov-th-note{{font-weight:400;color:var(--mut);font-size:.74rem;margin-left:4px}}
tr.ov-row{{cursor:pointer}}
tr.ov-row:hover td{{background:var(--bgs)}}
.ov-caption{{margin:14px 2px 0;font-size:.88rem;color:var(--mut);line-height:1.7}}
.ov-caption-top{{margin:-12px 2px 20px}}
.ov-caption b{{color:var(--ink)}}
.ov-caption-hint{{margin-left:10px;color:var(--ink);font-weight:500;white-space:nowrap}}
.ai-fab{{position:fixed;right:22px;bottom:22px;z-index:300;background:var(--ink);color:#fff;border:none;border-radius:24px;padding:11px 18px;font-size:.9rem;cursor:pointer;box-shadow:0 6px 24px rgba(20,20,30,.25);display:flex;align-items:center;gap:4px}}
.ai-fab:hover{{transform:translateY(-1px)}}
.ai-fab.hide{{display:none}}
#ai-fab-eg{{opacity:.85}}
.ask-drawer{{display:none;position:fixed;right:22px;bottom:22px;z-index:310;width:min(400px,calc(100vw - 32px));height:min(560px,calc(100vh - 60px));background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 48px rgba(20,20,30,.28);flex-direction:column;padding:16px 16px 14px}}
.ask-drawer.on{{display:flex}}
.ask-drawer-head{{display:flex;align-items:center;gap:10px}}
.ask-drawer-title{{font-weight:700}}
.ask-drawer-scope{{font-size:.78rem;color:var(--mut);background:var(--bgs);border-radius:10px;padding:1px 8px}}
.ask-drawer-scope:empty{{display:none}}
.ask-drawer-x{{margin-left:auto;background:none;border:none;font-size:1rem;cursor:pointer;color:var(--mut)}}
.ask-drawer-sub{{font-size:.78rem;color:var(--mut);margin:4px 0 8px}}
.ask-drawer .ask-result{{flex:1;overflow-y:auto;margin:8px 0}}
.ask-drawer .ask-bar{{margin-top:auto}}
@media(max-width:600px){{.ai-fab{{right:12px;bottom:12px}}.ask-drawer{{right:8px;bottom:8px}}}}
</style></head><body>

<nav><div class="wrap">
  <span class="brand">投顧戰績實驗室</span>
  <span class="sp"></span>
  <a href="/sql" id="nav-sql" class="nav-tab" style="text-decoration:none;border:1px solid var(--ink);border-radius:8px;padding:5px 13px;color:var(--ink);font-weight:600">SQL 遊樂場</a>
  <a href="/admin" id="nav-admin" class="nav-tab" style="display:none;text-decoration:none">⚙ 管理</a>
</div></nav>
<script>
// 管理鈕只在本機（localhost 開發模式）顯示；部署到公開站時自動隱藏
if(location.hostname==='localhost'||location.hostname==='127.0.0.1'){{
  var _na=document.getElementById('nav-admin');if(_na)_na.style.display='';
}}
// SQL 遊樂場需要後端（Athena）；GitHub Pages 靜態站沒有後端 → 自動隱藏，避免死連結
if(location.hostname.indexOf('github.io')>=0){{
  var _ns=document.getElementById('nav-sql');if(_ns)_ns.style.display='none';
}}
</script>

<!-- ══ 第一頁：整體 ══ -->
<div id="page-overall" class="page on">

<div class="hero">
  <div class="wrap">
    <h1>投顧戰績，逐筆驗算</h1>
    <p class="verdict-line">{_hero_n} 位財經網紅、{_hero_n_calls:,} 句喊盤，每一句都用真實股價算帳。經嚴格統計校正後，<b>{_hero_verdict_txt}</b>能證明打敗大盤。下方 ${_hero_med_f:.0f} 雖略高於 ${_hero_med_m:.0f}，但這點差距在統計上與丟銅板無異。</p>
    <div class="hero-duel">
      <div class="hd-side"><div class="hd-num">${_hero_med_f:.0f}</div><div class="hd-lbl">$100 跟著做</div></div>
      <div class="hd-vs">vs</div>
      <div class="hd-side"><div class="hd-num hd-mkt">${_hero_med_m:.0f}</div><div class="hd-lbl">$100 買大盤 <span class="info" data-tip="這裡的『大盤』不是單一指數，而是把每位分析師喊的每一筆，逐筆配對它自己該比的基準（個股比所屬市場指數、大盤/資產比自身買進持有），再加權累積成的『綜合大盤』。全站沿用這把尺；各人回測期不同，故取 {_hero_n} 人中位數。">i</span></div></div>
    </div>
    <div class="mast-foot">
      中位數（20 日持有）　·　中位方向命中 {_hero_med_dir:.0f}%（50% ＝ 丟銅板）　·　喊買前平均已漲 +{_hero_runup:.1f}%　·　資料 2020–2026：{_hero_n_calls:,} 次喊盤 + {_hero_n_sector} 次產業表態 + 20 條預言
    </div>
  </div>
</div>

<!-- ── 整體統計六區塊 ── -->
<section class="ov-section" id="overview">
  <div class="wrap">
    <div class="sec-h">
      <h2 class="stitle">全部分析師</h2>
      <span class="info" data-tip="用同一把尺量所有人：每人拿 $100，照他每一句喊盤買賣真實股價，看最後有沒有贏過他該比的大盤——打分的是市價，不是 AI 主觀評分。（技術：$100 calendar-time 固定資金組合、逐筆判尺，個股比所屬市場指數、大盤/資產比自身。）各人回測期長短不同，終值不可橫比，請看『年化超額』。">i</span>
    </div>
    <p class="ov-caption ov-caption-top">{cm_meta.get('kol_family',{}).get('n_raw_sig',10)} 位「未校正顯著」、多重比較校正後存活 <b>{cm_meta.get('kol_family',{}).get('n_fdr_sig',0)} 位</b>——同時檢定 {_hero_n} 個人，總會有人單憑運氣看起來顯著。<span class="ov-caption-hint">點任一列看完整分析 →</span></p>

    <div class="ov-sortbar">
      <span class="ov-sortbar-lbl">排序依</span>
      <div class="mtog">
        <button onclick="ovSort('raw',this)">跟他實賺</button>
        <button class="on" onclick="ovSort('excess12',this)">近12個月超額</button>
        <button onclick="ovSort('full',this)">全期年化超額</button>
      </div>
    </div>

    <!-- 排行榜表格（固定 20 日持有年化超額；其他天期/指標在各人卡片內） -->
    <div class="ov-tbl-wrap">
      <table class="ov-tbl" id="ov-tbl">
        <thead>
          <tr>
            <th class="ov-th-name">分析師</th>
            <th class="ov-th-raw">實賺 <span class="info tr" data-tip="跟著他做、近12個月實際賺到的累積 %（含大盤漲幅、還沒扣掉大盤）。牛市裡這數字大多是市場給的，不代表本事——真本事看『超額』。下方小字為同期綜合大盤。">i</span></th>
            <th class="ov-th-val2" id="ov-th-val">近12月超額 <span class="info tr" data-tip="同一段時間、同一個算法：實賺 − 同期綜合大盤 = 此欄，三個數字對得起來。範圍近12個月（2025-06～2026-06）。與最右『統計』欄不同源、不同算法（那欄是全期年化）。">i</span></th>
            <th class="ov-th-val">全期年化超額 <span class="info tr" data-tip="用各人完整追蹤期算、換成『每年』的超額（追蹤期長短不一，須年化才能橫向比）。因為是年化、又是全期，數字自然跟左邊近12個月的累積不相等。固定 20 日持有；5–250 日可在卡片內切換。">i</span></th>
            <th class="ov-th-fdr">統計 <span class="info tr" data-tip="這欄回答：扣掉運氣後，他贏大盤是真的嗎？同時檢定這麼多人，總會有幾個純靠運氣看起來很準，所以要做『多重比較校正』把僥倖的刷掉。（技術：週分批報酬 ＋ Romano-Wolf stepdown、circular block bootstrap，控 FWER、考慮天期相關；全體單一家族 {cm_meta.get('kol_family',{}).get('n_tests',65)} 檢定、未校正顯著 {cm_meta.get('kol_family',{}).get('n_raw_sig',10)} 個、校正後存活 {cm_meta.get('kol_family',{}).get('n_fdr_sig',0)} 個。）偵測下限約 {MDE_ANN:.0f}%/年——『無顯著』＝偵測不到，非證明沒有。">i</span></th>
          </tr>
        </thead>
        <tbody id="ov-tbody"></tbody>
      </table>
    </div>
  </div>
</section>

<section class="alt" id="why">
  <div class="wrap">
    <div class="sec-h">
      <h2 class="stitle">自己選人比一比</h2>
      <span class="info" data-tip="勾選想看的人，圖即時畫出他們各自「$100 跟他」的成長，旁邊列出對自己大盤的終值。各人回測期／市場不同，終值不能跨人比。">i</span>
      <span id="cmp-note" class="cmp-howto"></span>
    </div>

    <div class="cmp-bar">
      <div class="cmp-tabs">
        <button class="cmp-tab on" onclick="setCmpTab('curve',this)">成長曲線</button>
        <button class="cmp-tab" onclick="setCmpTab('event',this)">喊買時機</button>
      </div>
      <span class="cmp-sp"></span>
      <div class="cmp-add-wrap">
        <button class="cmp-add-btn" id="cmp-add-btn" onclick="toggleCmpAdd(event)">＋ 加入分析師</button>
        <div class="cmp-add-panel" id="cmp-add-panel">
          <div id="cmp-add-list"></div>
        </div>
      </div>
      <button class="cmp-add-btn" onclick="cmpReset()">還原預設</button>
      <button class="cmp-add-btn" onclick="cmpAll(false)">清空</button>
    </div>
    <svg id="cmp-chart" viewBox="0 0 800 300" preserveAspectRatio="xMidYMid meet"></svg>
    <svg id="ev-chart" viewBox="0 0 800 280" preserveAspectRatio="xMidYMid meet" style="display:none"></svg>
    <div class="cmp-legend" id="cmp-legend"></div>
  </div>
</section>
<script>var WALL={wall_json};var EVENT={event_json};var OVERVIEW={overview_json};
(function(){{
  var ov=OVERVIEW;
  var GREEN='#1a8754',RED='#c0392b',BLUE='#2563eb',MUT='#6f7680';
  var TYPE_LABEL={{call:'個股選股型',macro:'產業主題型',myst:'大盤擇時型'}};
  var BADGE_TIP='通過單次 t 檢定但未過多重比較校正（同時測很多人時容易雜訊冒出顯著）——不代表績效好壞，只代表「跟大盤有落差」，方向見左側數字顏色。';
  var FDR_BADGE={{
    fdr:'<span class="verdict-badge vb-fdr" title="通過 Romano-Wolf 多重比較校正，統計上站得住腳">校正後存活</span>',
    raw:'<span class="verdict-badge vb-raw" title="'+BADGE_TIP+'">未校正顯著</span>',
    none:'<span class="verdict-badge vb-none" title="偵測不到跟大盤有顯著差異（樣本不足或效果太小），非證明沒差">無顯著</span>'
  }};

  // ── 指標定義 ──
  var METRICS={{
    final:{{
      label:'終值 · 比大盤',
      applicable:['call','macro','myst'],
      getValue:function(r,h){{
        var b=r.byh[h]; if(!b||b.final==null||b.mkt==null||!b.mkt)return null;
        return Math.round((b.final/b.mkt-1)*100);
      }},
      fmt:function(v){{return v!=null?(v>=0?'+':'')+v+'%':null;}},
      detailFmt:function(r,h){{
        var b=r.byh[h]; if(!b||b.final==null||b.mkt==null)return null;
        return '$'+Math.round(b.final)+' vs $'+Math.round(b.mkt);
      }},
      isCentered:true,isPositiveGood:true
    }},
    excess_ann:{{
      label:'年化超額',thLabel:'年化超額 ↕',
      applicable:['call','macro','myst'],
      getValue:function(r,h){{return r.byh[h]?r.byh[h].excess_ann:null;}},
      fmt:function(v){{return v!=null?(v>=0?'+':'')+v+'%':null;}},
      detailFmt:function(r,h){{
        var f=r.byh[h]?r.byh[h].final:null,m=r.byh[h]?r.byh[h].mkt:null;
        return (f!=null&&m!=null)?'$'+Math.round(f)+' vs $'+Math.round(m):null;
      }},
      isCentered:true,
      isPositiveGood:true,
      summary:function(rows,h){{
        var vals=rows.filter(function(r){{return r.byh[h]&&r.byh[h].excess_ann!=null;}});
        if(!vals.length)return '';
        var pos=vals.filter(function(r){{return r.byh[h].excess_ann>0;}}).length;
        return '天期 '+h+' 日，共 '+vals.length+' 位有數據，其中 <b>'+pos+' 位</b>年化超額為正（>0%）。';
      }}
    }},
    winrate:{{
      label:'贏大盤率',thLabel:'贏大盤率 ↕',
      applicable:['call','macro'],
      getValue:function(r,h){{return r.byh[h]?r.byh[h].winrate:null;}},
      fmt:function(v){{return v!=null?v+'%':null;}},
      detailFmt:function(r,h){{return null;}},
      isCentered:true,
      centerAt:50,isPositiveGood:true,
      summary:function(rows,h){{
        var vals=rows.filter(function(r){{return r.byh[h]&&r.byh[h].winrate!=null;}});
        if(!vals.length)return '';
        var above=vals.filter(function(r){{return r.byh[h].winrate>50;}}).length;
        return '贏大盤率 > 50% 的有 <b>'+above+' 位</b>（基準：50%＝丟銅板）。大盤擇時型不適用此指標。';
      }}
    }},
    alpha:{{
      label:'選股 α',thLabel:'選股 α ↕',
      applicable:['call','macro'],
      getValue:function(r,h){{return r.byh[h]?r.byh[h].alpha:null;}},
      fmt:function(v){{return v!=null?(v>=0?'+':'')+v+'%':null;}},
      detailFmt:function(r,h){{return null;}},
      isCentered:true,isPositiveGood:true,
      summary:function(rows,h){{
        return '選股 α = 扣掉市場漲幅（β × 大盤）後剩下的超額報酬。正 = 選股有加分；負 = 選標的還不如直接買大盤。';
      }}
    }},
    runup:{{
      label:'喊買前追漲',thLabel:'喊買前追漲 ↕',
      applicable:['call','macro'],
      getValue:function(r,h){{return r.runup;}},
      fmt:function(v){{return v!=null?'+'+v+'%':null;}},
      detailFmt:function(r,h){{return null;}},
      isCentered:false,
      summary:function(rows,h){{
        var vals=rows.filter(function(r){{return r.runup!=null;}});
        if(!vals.length)return '';
        var avg=vals.reduce(function(s,r){{return s+r.runup;}},0)/vals.length;
        return '喊買前 20 日平均追漲 <b>+'+avg.toFixed(1)+'%</b>——越高越像在描述已發生的漲勢，而非預測。';
      }}
    }},
    dir_rate:{{
      label:'方向命中率',
      applicable:['call','macro','myst'],
      getValue:function(r,h){{return r.byh[h]?r.byh[h].hit_rate:null;}},
      fmt:function(v){{return v!=null?v+'%':null;}},
      detailFmt:function(r,h){{return r.type==='myst'?'大盤漲跌':'個股漲跌';}},
      isCentered:true,centerAt:50,isPositiveGood:true
    }}
  }};

  // ── Cell 迷你橫條 ──
  function miniBar(v,m,isCentered,centerAt,isPositiveGood){{
    if(v==null)return '';
    var c0=centerAt!=null?centerAt:0;
    var pos=(v-c0)>=0;
    var col=(isPositiveGood!=null)?(pos?GREEN:RED):BLUE;
    if(isCentered){{
      var half=Math.min(Math.abs(v-c0)/Math.max(Math.abs(v-c0)+0.01,30)*44,44);
      var fill=pos?('left:50%;width:'+half+'%;border-radius:0 3px 3px 0'):('right:50%;width:'+half+'%;border-radius:3px 0 0 3px');
      return '<div class="mc-track"><div class="mc-zero"></div><div class="mc-fill" style="'+fill+';background:'+col+'"></div></div>';
    }} else {{
      var pct=Math.min(Math.abs(v)/Math.max(Math.abs(v)+0.01,100)*88,88);
      return '<div class="mc-track-s"><div class="mc-fill-s" style="width:'+pct+'%;background:'+col+'"></div></div>';
    }}
  }}

  // 指標說明（收進欄標題 ⓘ）
  var METRIC_TIP={{
    final:'「$100 跟著做」的累積終值，相對「$100 買大盤」多賺／少賺幾 %。0% ＝ 跟大盤打平。絕對 $ 見右欄。',
    excess_ann:'扣掉同期大盤後，每年多賺／少賺幾 %。注意：追蹤期短的人是把短期間外推成一年，數字會被放大、較不穩——可參考筆數與右側統計欄。',
    winrate:'每筆預測贏過同期大盤的比率，50% ＝ 丟銅板。大盤擇時型不適用。',
    alpha:'扣掉市場漲幅（β × 大盤）後剩下的超額；正＝選股有加分。',
    runup:'喊買「前」20 日股價已平均漲多少；越高越像追已發生的漲勢。',
    dir_rate:'猜方向對的比率，50% ＝ 丟銅板。大盤擇時型＝猜大盤漲跌；個股/產業型＝喊買後個股漲跌。'
  }};
  // 基準 ticker → 中文（綜合大盤 hover 用）
  var BENCH_CN={{SPY:'美股',TAIEX:'台股',EWT:'台股',GLD:'黃金','BTC-USD':'比特幣',FXI:'A股',EWH:'港股',DBC:'原物料',SOXX:'半導體',TLT:'美債'}};
  var _ovSort='excess12';   // 排序欄：raw｜excess12（預設）｜full
  window.ovSort=function(k,btn){{_ovSort=k;if(btn){{btn.parentNode.querySelectorAll('button').forEach(function(b){{b.classList.remove('on');}});btn.classList.add('on');}}drawOvTable();}};
  // ── drawOvTable（固定 20 日年化超額；全期＋近12個月兩欄並排）──
  window.drawOvTable=function(){{
    var metricK='excess_ann';
    var h='20';
    var met=METRICS[metricK];
    var rows=ov.table_rows.slice();

    // 標記適用性（依每筆 call 組成的指標可用性，非人分類）
    rows=rows.map(function(r){{
      var applicable=met.applicable.indexOf(r.type)>=0;
      var v=applicable?met.getValue(r,h):null;                 // 全期年化
      var v1=applicable&&r.excess_1y!=null?r.excess_1y:null;    // 近12個月（同一段日曆）
      return {{r:r,v:v,v1:v1,applicable:applicable}};
    }});

    // 排序：依使用者點選的欄（raw＝跟他實賺｜full＝全期年化｜預設 excess12＝近12個月超額），降序；無值排後
    function sv(x){{
      if(_ovSort==='raw')return (x.applicable&&x.r.raw_1y!=null)?x.r.raw_1y:null;
      if(_ovSort==='full')return x.v;
      return x.v1;
    }}
    rows.sort(function(a,b){{
      var av=sv(a),bv=sv(b);
      if(av!=null&&bv!=null)return bv-av;
      if(av!=null)return -1;
      if(bv!=null)return 1;
      return 0;
    }});

    var numHTML=function(val){{
      if(val==null)return '<span class="ov-na">—</span>';
      var c=val>0?GREEN:(val<0?RED:MUT);
      return '<span class="ov-val-num" style="color:'+c+'">'+met.fmt(val)+'</span>';
    }};

    // 畫列
    var tbody=document.getElementById('ov-tbody');
    if(!tbody)return;
    tbody.innerHTML=rows.map(function(x,i){{
      var r=x.r,v=x.v,v1=x.v1,ok=x.applicable;
      // 視覺條只出現在「當前排序欄」
      var sVal=sv(x);
      var bar=sVal!=null?miniBar(sVal,null,met.isCentered,met.centerAt,met.isPositiveGood):'';
      var fdrBadge=r.fdr?FDR_BADGE[r.fdr]||'':'';
      if(r.fdr==='raw'&&ok&&v!=null&&v<0){{
        fdrBadge='<span class="verdict-badge vb-raw vb-raw-neg" title="'+BADGE_TIP+'　此列為負值：統計上顯著跑輸大盤">未校正顯著·跑輸</span>';
      }}
      var dimClass=(sVal==null)?' ov-row-dim':'';
      var open=r.mid?' onclick="openCard(\\''+r.uid+'\\',\\''+r.mid+'\\')"':'';
      var mo='';
      if(r.span){{var _p=r.span.split('～');if(_p.length===2){{var _a=_p[0].split('-'),_b=_p[1].split('-');var _n=(_b[0]-_a[0])*12+(_b[1]-_a[1]);if(_n>0)mo=' · 共'+_n+'個月';}}}}
      var sub=(r.n_calls!=null?r.n_calls.toLocaleString()+' 筆':'')+(r.span?' · '+r.span:'')+mo;
      // 原始報酬（含大盤）：淡化、方向色但不當評分；下方標同期大盤防裸報酬誤導
      var raw=ok&&r.raw_1y!=null?r.raw_1y:null;
      // 綜合大盤組成 → hover 說明（證明是逐筆配對 blend，非單一指數）
      var blendTip='';
      if(r.mkt_blend&&r.mkt_blend.length){{
        var parts=r.mkt_blend.map(function(b){{var nm=BENCH_CN[b.tk]||b.tk;return nm+' '+b.n.toLocaleString()+'筆 '+(b.ret==null?'—':((b.ret>0?'+':'')+b.ret+'%'));}});
        blendTip=' data-tip="綜合大盤＝逐筆配對各自基準、加權累積（非單一指數）。近12個月組成：'+parts.join('｜')+'"';
      }}
      // 實賺數字 與 大盤 子行 分開，好把 bar 插在「數字右邊、大盤上面」（排此欄時）
      var rawNum=raw!=null
        ?('<span class="ov-raw-num" style="color:'+(raw>0?GREEN:(raw<0?RED:MUT))+'">'+(raw>0?'+':'')+raw+'%</span>')
        :'<span class="ov-na">—</span>';
      var rawMkt=(raw!=null&&r.mkt_1y!=null)?('<span class="ov-raw-mkt ov-mkt-tip"'+blendTip+'>大盤 '+(r.mkt_1y>0?'+':'')+r.mkt_1y+'% ⓘ</span>'):'';
      return '<tr class="ov-row'+dimClass+'"'+open+'>'
        +'<td class="ov-td-name">'+r.name+'<span class="ov-td-track">'+sub+'</span></td>'
        +'<td class="ov-td-raw"><div class="ov-raw-flex"><div class="ov-raw-stack">'+rawNum+rawMkt+'</div>'+(_ovSort==='raw'?bar:'')+'</div></td>'
        +'<td class="ov-td-val2">'+(ok&&v1!=null?numHTML(v1)+(_ovSort==='excess12'?bar:''):'<span class="ov-na">—</span>')+'</td>'
        +'<td class="ov-td-val">'+numHTML(v)+(_ovSort==='full'?bar:'')+'</td>'
        +'<td class="ov-td-fdr">'+fdrBadge+'</td>'
        +'</tr>';
    }}).join('');
  }};

  drawOvTable();
}})();
</script>

<footer>
  <div class="wrap">
    <div class="foot-scope-line">
      <span>能問什麼<span class="info up" data-tip="能回答：他過去的績效、他當時怎麼說（逐字稿原話）、那次結果賺賠（引擎數字）。不能回答：未來會不會贏、崩盤時如何（回測期為多頭）。">i</span></span>
      <span>資料範圍<span class="info up" data-tip="資料 2020–2026：10 個台股投顧頻道 4,541 部、股癌 668 集（含逐字稿向量索引 29,144 塊）、鄭博見 218 部；{_hero_n_calls:,} 次喊盤 + {_hero_n_sector} 次產業表態 + 20 條預言。">i</span></span>
      <span>AI 問答<span class="info up" data-tip="你用白話問，它幫你查資料庫、用逐字稿原話＋數字回答——命中率、賺賠都是引擎算出來的，AI 不自己算數字，只負責讀懂問題和組織答案。（技術：query_calls 查命中/賺賠、search_transcript 本機向量檢索逐字稿 bge-small-zh，DeepSeek 只做語言、數字一律引擎出。）">i</span></span>
      <span>限制<span class="info up" data-tip="回測期為多頭，不外推空頭；>半年的存股論述不評；{LIMITUP_FRAC:.1f}% 喊盤進場日漲停買不到、真實跟單更差；LLM 抽樣複核約 88–95% 正確；偵測下限約 {MDE_ANN:.0f}%/年（「未顯著」＝偵測不到，非證明沒有）；頻道為特定來源、僅評估做多訊號。">i</span></span>
      <span>源碼 Python / yfinance / statsmodels，歡迎複驗。</span>
    </div>
    <div class="foot-disc"><b>免責聲明：</b>本站為學術性數據研究，呈現公開可複驗的歷史統計，<b>不構成投資建議</b>，亦不對任何個人、頻道或機構之專業能力作評價。歷史績效不代表未來表現。</div>
  </div>
</footer>

</div><!-- /page-overall -->

<!-- ══ AI 抽屜（全站唯一 AI 入口；開著分析師卡時自動聚焦該人）══ -->
<button class="ai-fab" id="ai-fab" onclick="toggleAskDrawer()">💬 問 AI：<span id="ai-fab-eg">「{_ask_chips[0]}？」</span></button>
<div class="ask-drawer" id="ask-drawer">
  <div class="ask-drawer-head">
    <span class="ask-drawer-title">AI 問答</span>
    <span class="ask-drawer-scope" id="ask-scope"></span>
    <button class="ask-drawer-x" onclick="toggleAskDrawer()">✕</button>
  </div>
  <p class="ask-drawer-sub">AI 即時呼叫引擎查數據、翻逐字稿原話。所有數字由引擎算，非 AI 自己編。</p>
  <div class="ask-chips">{_ask_chips_html}</div>
  <div class="ask-result" id="ask-result">
    <div class="ask-empty" id="ask-empty"><div class="ask-icon">💬</div>輸入問題，或點擊上方範例。可接著追問，AI 會記得上文。</div>
    <div class="ask-log" id="ask-log"></div>
  </div>
  <div class="ask-bar">
    <input type="text" id="ask-input" placeholder="問個問題…" onkeydown="if(event.key==='Enter')askAI()">
    <button class="ask-btn" id="ask-btn" onclick="askAI()">送出</button>
  </div>
</div>

<!-- modal store（個人頁右側 pane 用，整體頁 grid 卡片點開也用） -->
<div id="modal-store">{modals_html}</div>

<script>
// _cm initialized in <head>
function scaleCI(v){{return 50+Math.max(-50,Math.min(50,v/1.6));}}
// ── 統一反應式引擎：天數＋方向 → 一次重繪兩部分 ──
// ── 排行榜列 → 分析師卡 overlay（可分享網址 #/uid）──
var _rpCurrent=null;   // 保留給 openModal 的取回邏輯（恆為 null，右側 pane 已移除）
var _cardOpen=null;    // 目前開著的 {{uid,mid,name}}
function openCard(uid,mid){{
  openModal(mid||uid);
  var m=document.getElementById('modal-'+(mid||uid));
  var nmEl=m?m.querySelector('.pname'):null;
  _cardOpen={{uid:uid,mid:mid||uid,name:nmEl?nmEl.textContent.trim():uid}};
  history.replaceState(null,'','#/'+encodeURIComponent(uid));
  askScopeRedraw();
}}
// ── AI 抽屜 ──────────────────────────────────────────
// 靜態託管（無後端）時自動隱藏 AI 問答：ping /api/analysts，失敗就整組收起來
fetch('/api/analysts').then(function(r){{if(!r.ok)throw 0;}}).catch(function(){{
  var f=document.getElementById('ai-fab'),d=document.getElementById('ask-drawer');
  if(f)f.style.display='none'; if(d)d.style.display='none';
}});
var _fabEgs={_fab_egs_js};
var _fabI=0;
setInterval(function(){{var el=document.getElementById('ai-fab-eg');if(!el)return;_fabI=(_fabI+1)%_fabEgs.length;el.textContent=_fabEgs[_fabI];}},6000);
function toggleAskDrawer(){{
  var d=document.getElementById('ask-drawer');
  var open=d.classList.toggle('on');
  document.getElementById('ai-fab').classList.toggle('hide',open);
  if(open){{askScopeRedraw();var i=document.getElementById('ask-input');if(i)i.focus();}}
}}
function askScopeRedraw(){{
  var s=document.getElementById('ask-scope');
  if(s)s.textContent=_cardOpen?('聚焦：'+_cardOpen.name):'';
}}
// hash routing：#/uid 直接開該分析師卡（可分享）
document.addEventListener('DOMContentLoaded',function(){{
  var h=location.hash;
  if(h.indexOf('#/')===0){{
    var uid=decodeURIComponent(h.slice(2));
    var row=(OVERVIEW.table_rows||[]).filter(function(r){{return r.uid===uid;}})[0];
    if(row&&row.mid)openCard(row.uid,row.mid);
  }}
}});
function _fUSD(v){{return '$'+Math.round(v).toLocaleString();}}
function _sgn(v){{return (v>=0?'+':'')+v.toFixed(1);}}
function sparkSVG(curve,mcurve){{
  var w=260,h=64,pad=4,all=curve.concat(mcurve);
  var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),rng=(hi-lo)||1;
  function P(a){{var n=a.length;return a.map(function(v,i){{
    return (pad+(w-2*pad)*i/(n-1)).toFixed(1)+','+(h-pad-(h-2*pad)*(v-lo)/rng).toFixed(1);}}).join(' ');}}
  return '<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" class="spark">'+
    '<polyline points="'+P(mcurve)+'" fill="none" stroke="#d2d6dc" stroke-width="1.5"/>'+
    '<polyline points="'+P(curve)+'" fill="none" stroke="#16161f" stroke-width="1.8"/></svg>';
}}
function _ddOf(c){{var pk=c[0],dd=0;for(var i=0;i<c.length;i++){{if(c[i]>pk)pk=c[i];var d=(c[i]/pk-1)*100;if(d<dd)dd=d;}}return dd;}}
function _ciHTML(a,lo,hi,p,fdr,raw){{
  if(a==null||lo==null||hi==null)return '<div class="rnote">此天期無「做多超額」可估。</div>';
  var cov=(lo<=0&&0<=hi),col=cov?'#6b7280':(a>0?'#1a8754':'#c0392b');
  var mark=fdr?' <b style="color:#1a8754">✓校正後存活</b>':(raw?' <span style="color:#8a8f98">*未校正顯著</span>':'');
  return '<div class="ci-wrap"><div class="ci-row"><span>持有期間年化超額 '+_sgn(a)+'%（p='+p.toFixed(3)+'）'+mark+'</span>'+
    '<span>95% CI ['+lo.toFixed(0)+'%, '+hi.toFixed(0)+'%]</span></div>'+
    '<div class="ci-track"><div class="ci-zero"></div>'+
    '<div class="ci-range" style="left:'+scaleCI(lo)+'%;width:'+Math.min(100,Math.max(1,(hi-lo)/1.6))+'%;background:'+col+'33;border:1.5px solid '+col+'"></div>'+
    '<div class="ci-dot" style="left:'+scaleCI(a)+'%;background:'+col+'"></div></div></div>';
}}
function _box(hdr,cells){{return '<div class="lsect3"><div class="lsect3-hdr">'+hdr+'</div><div class="pstats" style="grid-template-columns:repeat('+cells.length+',1fr)">'+
  cells.map(function(c){{return '<div class="pstat"><div class="pstat-v" style="color:'+c[1]+'">'+c[0]+'</div><div class="pstat-l">'+c[2]+'</div></div>';}}).join('')+'</div></div>';}}
// 比例條：綠命中／紅未中／灰待定，寬度=比例（全卡共用、跟著天數/方向變）
function hitbarHTML(uid,r,dir,base){{
  var m=_cmM[uid],hit,miss,pend,lpos,lneg;
  if(m.is_mb){{
    // 預言型：基準切到 mkt 時大盤vs大盤永遠平手，不顯示比例條
    if(base==='mkt')return '';
    var key=dir==='long'?'bull':(dir==='short'?'bear':'all');
    var dd=m.dir[key]; if(!dd||dd.rate==null||dd.n===0)return '';
    hit=Math.round(dd.n*dd.rate/100); miss=dd.n-hit; pend=dd.pend||0;
    lpos='方向命中'; lneg='方向未中';
  }} else {{
    var hc=r.hc; if(!hc)return '';
    var L=hc.long||{{hit:0,miss:0,pend:0}}, S=hc.short||{{hit:0,miss:0,pend:0}};
    if(dir==='short'){{
      if((S.hit+S.miss+S.pend)===0)return '';
      hit=S.hit; miss=S.miss; pend=S.pend; lpos='看空命中'; lneg='看空未中';
    }} else if(dir==='both'){{
      hit=L.hit+S.hit; miss=L.miss+S.miss; pend=L.pend+S.pend; lpos='命中'; lneg='未中';
    }} else {{
      // 做多長多：profit 基準用 hit_rate 近似計算（settled counts 相同）
      if(base==='profit'&&r.hit_rate!=null){{
        var settled0=L.hit+L.miss;
        hit=Math.round(r.hit_rate/100*settled0); miss=settled0-hit; pend=L.pend;
        lpos='有賺'; lneg='虧損';
      }} else {{
        hit=L.hit; miss=L.miss; pend=L.pend; lpos='贏大盤'; lneg='輸大盤';
      }}
    }}
  }}
  var settled=hit+miss, tot=settled+pend; if(!tot)return '';
  var gp=hit/tot*100,rp=miss/tot*100,yp=pend/tot*100;
  var pct=settled?Math.round(hit/settled*100):0;
  return '<div class="hitbar" title="'+lpos+' '+hit+'｜'+lneg+' '+miss+'｜待定 '+pend+'">'+
    '<div class="hb-g" style="width:'+gp+'%"></div><div class="hb-r" style="width:'+rp+'%"></div><div class="hb-y" style="width:'+yp+'%"></div></div>'+
    '<div class="hb-leg"><span><b style="color:#1a8754">■</b> '+lpos+' '+hit+'（'+pct+'%）</span>'+
    '<span><b style="color:#c0392b">■</b> '+lneg+' '+miss+'</span>'+
    '<span><b style="color:#cfd4da">■</b> 待定 '+pend+'</span></div>';
}}
function _pendBar(n){{
  if(!n)return '';
  return '<div class="hitbar" title="待定 '+n+'"><div class="hb-y" style="width:100%"></div></div>'+
    '<div class="hb-leg"><span><b style="color:#cfd4da">■</b> 待定 '+n+'（100%，預測期未到）</span></div>';
}}
function _p2HTML(uid,r,dir,base){{
  var m=_cmM[uid],bar=hitbarHTML(uid,r,dir,base);
  if(m.is_mb){{
    var key0=dir==='long'?'bull':(dir==='short'?'bear':'all');
    // 預言型切到「比大盤」：大盤 vs 大盤 = 永遠平手；給完整數字格＋平手條，結構對齊「方向對沒」
    if(base==='mkt'){{
      var dd0=m.dir[key0]||{{n:0,pend:0}}, tieN=(dd0.n||0)+(dd0.pend||0);
      var tieBar='<div class="hitbar" title="全部平手"><div class="hb-y" style="width:100%"></div></div>'+
        '<div class="hb-leg"><span><b style="color:#cfd4da">■</b> 與大盤平手 '+tieN+'（100%）</span></div>';
      return _box('比大盤（教育用途）',[['0%','#6b7280','贏大盤率'],['平手','#6b7280','大盤 vs 大盤']])+
        tieBar+
        '<div class="rnote">純擇時＝賭大盤本身，跟他做就是抱大盤／轉現金，對大盤的超額恆為 0。這就是為何裁判用「方向對沒」、而非「比大盤」。</div>';
    }}
    var key=dir==='long'?'bull':(dir==='short'?'bear':'all');
    var dd=m.dir[key],hdr=dir==='long'?'看漲方向':(dir==='short'?'看跌方向':'整體方向（看漲＋看跌）');
    if(!dd||dd.n===0||dd.rate==null){{
      var pn=(dd&&dd.pend)||0;
      return _box(hdr,[['—','#9aa0a8','方向命中率'],[pn+'','inherit','待定（預測期未到）']])+
        _pendBar(pn)+
        '<div class="rnote">'+(pn?'此方向有 '+pn+' 條預言尚未到期，無已結算紀錄。':'此方向無預言。')+'</div>';
    }}
    var col=dd.rate>55?'#1a8754':(dd.rate<45?'#c0392b':'inherit');
    return _box(hdr,[[dd.rate.toFixed(0)+'%',col,'方向命中率'],[dd.n+'','inherit','已結算筆數']])+bar;
  }}
  if(dir==='short'){{
    if(r.short_hit==null)return _box('看空準度（不放空，僅記準度）',[['—','#9aa0a8','看空命中率'],['—','#9aa0a8','看空年化超額']])+
      '<div class="rnote">此天期無看空樣本。</div>';
    return _box('看空準度（不放空，僅記準度）',[[r.short_hit.toFixed(0)+'%',r.short_hit>=50?'#1a8754':'#c0392b','看空命中率'],[_sgn(r.short_excess_ann)+'%',r.short_excess_ann>0?'#1a8754':'#c0392b','看空年化超額']])+bar;
  }}
  if(dir==='both'){{
    var hcb=r.hc; var bBox='';
    if(hcb){{
      var L=hcb.long||{{hit:0,miss:0}},S=hcb.short||{{hit:0,miss:0}};
      var totH=L.hit+S.hit,totS=L.hit+L.miss+S.hit+S.miss;
      var bPct=totS?Math.round(totH/totS*100):0;
      var bCol=bPct>=50?'#1a8754':'#c0392b';
      bBox=_box('雙向命中率（做多+看空合計）',[[totH+' / '+totS,bCol,'命中 / 結算'],[bPct+'%',bCol,'合計命中率']]);
    }}
    return bBox+'<div class="note" style="margin:6px 0">雙向＝做多買進＋看空放空（假設你會放空）。$ 終值已反映於上方；他看空多半看錯時，雙向通常低於純做多。</div>'+bar;
  }}
  // 做多：依基準切換
  if(base==='profit'){{
    var hit=r.hit_rate;
    var hitCol=hit!=null&&hit>=50?'#1a8754':'#c0392b';
    return _box('有賺沒（以 0 為基準，多頭裡白送）',[[hit==null?'—':hit.toFixed(0)+'%',hitCol,'賺錢率']])+
      '<div class="rnote">切到「有賺沒」：只要正報酬就算中，多頭環境每筆幾乎都賺。切回「比大盤」看真實門檻。</div>'+bar;
  }}
  var beat=r.beat_mkt;
  return _box('做多準度（比大盤）',[[beat==null?'—':beat.toFixed(0)+'%',(beat!=null&&beat>=50?'#1a8754':'#c0392b'),'贏大盤率（週為單位）']])+bar+
    '<div class="rnote">上方 % 以『週』為單位（每週一批、贏大盤的週佔比）；下方長條以『逐筆喊盤』為單位（每筆贏／輸大盤的筆數），兩者單位不同，數字不會一樣。</div>';
}}
// 八欄表逐筆：依持有天數即時渲染
function _ricon(h){{return h=='hit'?'<span style="color:#1a8754;font-weight:700">✓</span>':(h=='miss'?'<span style="color:#c0392b;font-weight:700">✗</span>':'<span style="color:#aab0b8">⏳</span>');}}
function _rnum(v,color){{if(v==null)return '⏳';var s=_sgn(v)+'%';if(color){{var c=v>0?'#1a8754':(v<0?'#c0392b':'#6b7280');return '<span style="color:'+c+'">'+s+'</span>';}}return s;}}
function _esc(s){{return (s||'').replace(/"/g,'&quot;').replace(/</g,'&lt;');}}
function renderTable(uid,h){{
  var t=_tbl[uid];if(!t)return;
  var tb1=document.getElementById('tb1_'+uid),tb2=document.getElementById('tb2_'+uid);
  if(!tb1&&!tb2)return;
  var h1='',h2='';
  t.rows.forEach(function(r){{
    var d=r.byh[h];
    var dcol=r.dir=='看多'?'#1a8754':'#c0392b';
    var act=r.dir=='看多'?'買進':'轉現金';
    var dt=r.date.slice(0,10),sum=_esc(r.summary),ttl=_esc(r.full||r.summary);
    if(!d){{ // 該天期尚未到期（近期立場）
      h1+='<tr class="pend"><td>'+dt+'</td><td class="rsum" title="'+ttl+'">'+sum+'</td><td>'+act+'</td><td>'+dt+'+'+h+'日</td><td>⏳</td><td>⏳</td><td>⏳</td></tr>';
      h2+='<tr class="pend"><td>'+dt+'</td><td class="rsum" title="'+ttl+'">'+sum+'</td><td style="color:'+dcol+'">'+r.dir+'</td><td>'+dt+'+'+h+'日</td><td>⏳</td><td>'+_ricon('pending')+'</td></tr>';
      return;
    }}
    var cls=d.hit=='pending'?' class="pend"':'';
    h1+='<tr'+cls+'><td>'+dt+'</td><td class="rsum" title="'+ttl+'">'+sum+'</td><td>'+act+'</td><td>'+(d.period||'')+'</td><td>'+_rnum(d.strat,true)+'</td><td>'+_rnum(d.bench)+'</td><td>'+_rnum(d.excess,true)+'</td></tr>';
    h2+='<tr'+cls+'><td>'+dt+'</td><td class="rsum" title="'+ttl+'">'+sum+'</td><td style="color:'+dcol+'">'+r.dir+'</td><td>'+(d.period||'')+'</td><td>'+_rnum(d.excess,true)+'</td><td>'+_ricon(d.hit)+'</td></tr>';
  }});
  if(tb1)tb1.innerHTML=h1;
  if(tb2)tb2.innerHTML=h2;
}}
var _st={{}};
function _sel(btn){{btn.parentNode.querySelectorAll('button').forEach(function(b){{b.classList.remove('on');}});btn.classList.add('on');}}
// ── 第三部分：體檢表 JS ─────────────────────────────────
function _p3HTML(uid,h){{
  var m=_cmM[uid]; if(!m||!m.health)return'';
  var hd=m.health[h]; if(!hd)return'<div class="rnote">此天期無足夠已結算資料</div>';
  // 1. 贏過亂猜
  var beat=hd.beat,bclr=beat>55?'#1a8754':beat<45?'#c0392b':'#6b7280';
  var bnote=beat>55?'略高於丟銅板':(beat<45?'低於丟銅板':'與丟銅板相當');
  var row1=_hcRow('方向命中率','<span class="hc-big" style="color:'+bclr+'">'+beat+'%</span><div class="hc-note">'+bnote+'（丟銅板＝50%）</div>',_hcBar(beat,50,bclr));
  // 2. 報酬集中度
  var conc=hd.conc;
  var row2=conc!=null?_hcRow('集中度','<span class="hc-big">'+conc+'%</span><div class="hc-note">前20%喊單佔了'+conc+'%正超額</div>',_hcConc(conc)):_hcRow('集中度','<span class="hc-note">—</span>','');
  // 3. 贏/輸幅度
  var win=hd.win,loss=hd.loss;
  var row3=(win!=null)?_hcRow('贏/輸幅度','<span class="hc-big" style="color:#1a8754">+'+(win)+'%</span> <span class="hc-big" style="color:#c0392b">'+(loss||0)+'%</span><div class="hc-note">平均贏多少 vs 平均輸多少</div>',_hcWL(win,loss)):_hcRow('贏/輸幅度','<span class="hc-note">—</span>','');
  // 3b. 每筆期望（命中率×贏幅 +（1−命中率）×輸幅）
  var row3b='';
  if(win!=null){{
    var p=beat/100, exp=p*win+(1-p)*(loss||0);
    var eclr=exp>0?'#1a8754':(exp<0?'#c0392b':'#6b7280');
    row3b=_hcRow('每筆期望',
      '<span class="hc-big" style="color:'+eclr+'">'+(exp>0?'+':'')+exp.toFixed(1)+'%</span>'+
      '<div class="hc-note">命中率×贏幅 +（1−命中率）×輸幅<br>等權每筆平均超額，非組合 $ 結果</div>',
      _hcExp(exp));
  }}
  // 4. 滾動趨勢
  var rolling=hd.rolling||[];
  var row4=rolling.length>=2?_hcRow('近況趨勢','<div class="hc-note">'+rolling.length+'段命中率走勢（近期在右）</div>',_hcRoll(rolling)):_hcRow('近況趨勢','<span class="hc-note">—（資料不足）</span>','');
  // 5. 神單/雷單（摺疊）
  var top3=hd.top3||[],bot3=hd.bot3||[];
  var tfmt=function(c,clr){{return '<div class="hc-trade" title="'+_esc(c.full||c.t)+'"><span class="htk">'+_esc(c.t)+'</span><span class="hdt">'+c.d+'</span><span class="hex" style="color:'+clr+'">'+(c.e>0?'+':'')+c.e+'%</span></div>';}};
  var trades='<details class="hc-det"><summary>神單 / 雷單 ▸</summary><div class="hc-trades">'+
    top3.map(function(c){{return tfmt(c,'#1a8754');}}).join('')+
    '<hr class="hc-sep">'+
    bot3.slice().reverse().map(function(c){{return tfmt(c,'#c0392b');}}).join('')+
    '</div></details>';
  return '<div class="hc-wrap">'+row1+row2+row3+row3b+row4+trades+'</div>';
}}
function _hcRow(label,stat,vis){{return '<div class="hc-row"><div class="hc-label">'+label+'</div><div>'+stat+'</div><div>'+vis+'</div></div>';}}
function _hcBar(val,mark,clr){{
  var W=78,H=16,xv=Math.min(100,Math.max(0,val))/100*W,xm=mark/100*W;
  return '<svg width="'+W+'" height="'+H+'" style="overflow:visible"><rect x="0" y="4" width="'+W+'" height="8" rx="4" fill="#e5e7eb"/><rect x="0" y="4" width="'+xv.toFixed(1)+'" height="8" rx="4" fill="'+clr+'"/><line x1="'+xm.toFixed(1)+'" y1="1" x2="'+xm.toFixed(1)+'" y2="15" stroke="#374151" stroke-width="1.5" stroke-dasharray="2,1"/></svg>';
}}
function _hcConc(pct){{
  var W=78,xp=pct/100*W,xm=0.2*W;
  return '<svg width="'+W+'" height="16"><rect x="0" y="4" width="'+W+'" height="8" rx="4" fill="#e5e7eb"/><rect x="0" y="4" width="'+xp.toFixed(1)+'" height="8" rx="4" fill="#2563eb"/><line x1="'+xm.toFixed(1)+'" y1="1" x2="'+xm.toFixed(1)+'" y2="15" stroke="#374151" stroke-width="1.5" stroke-dasharray="2,1"/></svg>';
}}
function _hcWL(win,loss){{
  var absL=loss!=null?Math.abs(loss):0,mx=Math.max(Math.abs(win||0),absL,1),W=78;
  var ww=(Math.abs(win||0)/mx*W).toFixed(1),lw=(absL/mx*W).toFixed(1);
  return '<svg width="'+W+'" height="17"><rect x="0" y="0" width="'+ww+'" height="7" rx="3" fill="#1a8754"/><rect x="0" y="10" width="'+lw+'" height="7" rx="3" fill="#c0392b"/></svg>';
}}
function _hcExp(exp){{
  var W=78,H=16,half=W/2,mx=Math.max(Math.abs(exp),3),len=(Math.abs(exp)/mx*half).toFixed(1);
  var pos=exp>=0,clr=pos?'#1a8754':'#c0392b';
  var x=pos?half:(half-len);
  return '<svg width="'+W+'" height="'+H+'"><rect x="0" y="4" width="'+W+'" height="8" rx="4" fill="#f0f1f4"/>'+
    '<rect x="'+x+'" y="4" width="'+len+'" height="8" rx="2" fill="'+clr+'"/>'+
    '<line x1="'+half+'" y1="1" x2="'+half+'" y2="15" stroke="#c9ccd1" stroke-width="1.5"/></svg>';
}}
function _hcRoll(bins){{
  var W=78,H=30,pad=3,rates=bins.map(function(b){{return b.rate;}});
  var mn=Math.min.apply(null,rates),mx=Math.max.apply(null,rates),rng=Math.max(mx-mn,5);
  var dx=(W-pad*2)/Math.max(bins.length-1,1);
  var pts=rates.map(function(r,i){{return[(pad+i*dx).toFixed(1),(H-pad-(r-mn)/rng*(H-pad*2)).toFixed(1)];}});
  var path='M'+pts.map(function(p){{return p[0]+','+p[1];}}).join('L');
  var tclr=rates[rates.length-1]>=rates[0]?'#1a8754':'#c0392b';
  var y50=(H-pad-(50-mn)/rng*(H-pad*2)).toFixed(1);
  return '<svg width="'+W+'" height="'+H+'"><line x1="'+pad+'" y1="'+y50+'" x2="'+(W-pad)+'" y2="'+y50+'" stroke="#e5e7eb" stroke-width="1"/><path d="'+path+'" fill="none" stroke="'+tclr+'" stroke-width="2"/>'
    +pts.map(function(p,i){{return '<circle cx="'+p[0]+'" cy="'+p[1]+'" r="2.5" fill="'+(rates[i]>=50?'#1a8754':'#c0392b')+'"/>';}}).join('')+'</svg>';
}}
function setH(uid,h,btn){{(_st[uid]=_st[uid]||{{}}).h=h;_sel(btn);cmRender(uid);}}
function setBase(uid,b,btn){{(_st[uid]=_st[uid]||{{}}).base=b;_sel(btn);cmRender(uid);}}
function setDir(uid,d,btn){{(_st[uid]=_st[uid]||{{}}).dir=d;_sel(btn);cmRender(uid);}}
function cmRender(uid){{
  var hz=_cm[uid],m=_cmM[uid];if(!hz||!m)return;
  var st=_st[uid]=_st[uid]||{{}};
  if(!st.h)st.h='20'; if(!st.dir)st.dir=m.dir0||'long';
  if(!st.base)st.base=(m.baseline&&m.baseline.default)||'mkt';
  var r=hz[st.h]||hz['20']||hz[Object.keys(hz)[0]];if(!r)return;
  var dir=st.dir,base=st.base;
  // ── 第一部分：$ / 曲線 / 最大回撤 ──
  var follow,bench,curve,mcurve;
  if(m.p1){{follow=m.p1.follow;bench=m.p1.bench;curve=m.p1.curve;mcurve=m.p1.mcurve;}}
  else{{var mode=(r.modes&&r.modes[dir])||(r.modes&&r.modes.long)||{{follow_end:r.follow_end,curve:r.curve}};
    follow=mode.follow_end;bench=r.mkt_end;curve=mode.curve||[1,1];mcurve=r.mcurve||[1,1];}}
  var du=document.getElementById('du_'+uid);
  if(du){{var cls=follow>bench?'pos':(follow<bench?'neg':'flat');
    du.innerHTML='<div class="pside"><div class="pv '+cls+'">'+_fUSD(follow)+'</div><div class="pl">$100 跟他</div></div>'+
      '<div class="pvs">vs</div><div class="pside"><div class="pv mkt">'+_fUSD(bench)+'</div><div class="pl">$100 買'+m.bench_label+'</div></div>';}}
  var sp=document.getElementById('sp_'+uid);if(sp)sp.innerHTML=sparkSVG(curve,mcurve);
  var dd=document.getElementById('dd_'+uid);
  if(dd){{var v=(!m.p1&&dir==='long'&&r.max_drawdown!=null)?r.max_drawdown:_ddOf(curve);
    dd.innerHTML='策略最大回撤 <b style="color:'+(v<-20?'#c0392b':'inherit')+'">'+v.toFixed(0)+'%</b>';}}
  var vd=document.getElementById('vd_'+uid);
  if(vd&&m.verdicts)vd.innerHTML=m.verdicts[dir]||m.verdicts.long||'';
  var ci=document.getElementById('ci_'+uid);
  if(ci){{
    if(m.is_mb)ci.innerHTML='';
    else if(dir==='long')ci.innerHTML=_ciHTML(r.excess_ann,r.ci_lo,r.ci_hi,r.p,r.fdr_sig,r.raw_sig);
    else if(dir==='short')ci.innerHTML=(r.short_excess_ann!=null?'<div class="rnote">看空年化超額 '+_sgn(r.short_excess_ann)+'%（不放空、僅記準度，詳見下方第二部分）</div>':'<div class="rnote">此天期無看空樣本。</div>');
    else ci.innerHTML='<div class="rnote">雙向含放空；統計顯著性以「做多」腿為準（切回做多看校正結果）。</div>';
  }}
  // ── 第二部分：方向預測準度 + 逐筆交易紀錄表 ──
  var p2=document.getElementById('p2_'+uid);if(p2)p2.innerHTML=_p2HTML(uid,r,dir,base);
  if(_tbl[uid])renderTable(uid,st.h);
  // ── 第三部分：體檢表 ──
  var p3=document.getElementById('p3_'+uid);if(p3)p3.innerHTML=_p3HTML(uid,st.h);
}}

var curF='all', desc=true;
function setFilter(f,btn){{
  curF=f;
  document.querySelectorAll('.chip[data-f]').forEach(function(b){{
    b.classList.toggle('on', b.dataset.f===f);
  }});
  apply();
}}
function apply(){{
  var q=document.getElementById('search').value.trim();
  document.querySelectorAll('.ncard').forEach(function(c){{
    var okF = curF==='all' || c.dataset.type===curF;
    var okQ = q==='' || c.dataset.name.indexOf(q)>=0;
    c.style.display = (okF&&okQ)?'':'none';
  }});
}}
function toggleSort(btn){{
  desc=!desc;
  btn.textContent = desc?'↓ 依績效':'↑ 依績效';
  var g=document.getElementById('grid');
  [].slice.call(g.querySelectorAll('.ncard')).sort(function(a,b){{
    var d=parseFloat(b.dataset.excess)-parseFloat(a.dataset.excess);
    return desc?d:-d;
  }}).forEach(function(c){{g.appendChild(c)}});
}}
function openModal(id){{
  // 如果右側 pane 已挪走這個 modal-box，先取回再開
  if(_rpCurrent===id){{
    var pane=document.getElementById('rp-content');
    var box=pane&&pane.querySelector('.modal-box');
    if(box){{var ms=document.getElementById('modal-'+id);if(ms)ms.appendChild(box);_rpCurrent=null;}}
  }}
  var store=document.getElementById('modal-store');
  if(store)store.style.display='';
  var m=document.getElementById('modal-'+id); if(!m) return;
  m.classList.add('on'); m.style.display=''; document.body.classList.add('modal-open');
}}
function closeModal(){{
  document.querySelectorAll('.modal.on').forEach(function(m){{m.classList.remove('on');m.style.display='';}} );
  document.body.classList.remove('modal-open');
  var store=document.getElementById('modal-store');
  if(store)store.style.display='none';
  _cardOpen=null;
  if(location.hash.indexOf('#/')===0)history.replaceState(null,'',location.pathname+location.search);
  askScopeRedraw();
}}
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeModal();}});
// 初次繪製每張卡的反應式內容
document.addEventListener('DOMContentLoaded',function(){{(window._inits||[]).forEach(function(u){{try{{cmRender(u);}}catch(e){{}}}});}});
// ── 即時 hover 提示：立場摘要／神單雷單被截斷時，移上去馬上顯示完整原文 ──
// 附在 body（position:fixed）→ 不會被可捲動表格 overflow 裁切；跟著游標、近邊緣自動翻邊。
(function(){{
  var tip=document.createElement('div');
  tip.style.cssText='position:fixed;z-index:99999;max-width:340px;background:#16161f;color:#fff;'
    +'font-size:.78rem;line-height:1.55;padding:9px 12px;border-radius:8px;'
    +'box-shadow:0 8px 26px rgba(0,0,0,.24);pointer-events:none;display:none;white-space:normal';
  document.body.appendChild(tip);
  var SEL='.rsum,.hc-trade,.ov-mkt-tip,.info';
  function txtOf(el){{return el.getAttribute('data-tip')||el.getAttribute('title')||'';}}
  function place(cx,cy){{
    var x=cx+14,y=cy+18,w=tip.offsetWidth,h=tip.offsetHeight;
    if(x+w>window.innerWidth-8)x=cx-w-14;          // 靠右邊緣 → 翻到左邊
    if(y+h>window.innerHeight-8)y=cy-h-18;          // 靠下緣 → 翻到上面
    tip.style.left=Math.max(8,x)+'px'; tip.style.top=Math.max(8,y)+'px';
  }}
  document.addEventListener('mouseover',function(e){{
    var el=e.target.closest&&e.target.closest(SEL); if(!el)return;
    if(el.hasAttribute('title')){{el.setAttribute('data-tip',el.getAttribute('title'));el.removeAttribute('title');}}
    var t=txtOf(el); if(!t)return;
    tip.textContent=t; tip.style.display='block'; place(e.clientX,e.clientY);   // 一移上去就定位（不必等移動）
  }});
  document.addEventListener('mousemove',function(e){{
    if(tip.style.display==='block')place(e.clientX,e.clientY);
  }});
  document.addEventListener('mouseout',function(e){{
    if(e.target.closest&&e.target.closest(SEL))tip.style.display='none';
  }});
}})();
function showPane(i,btn){{
  document.querySelectorAll('.tab').forEach(function(t,j){{t.classList.toggle('on',j===i)}});
  document.querySelectorAll('.pane').forEach(function(p,j){{p.classList.toggle('on',j===i)}});
}}
// ── 自選淨值實驗台 ──
var CMP_PAL=['#16161f','#1a8754','#c0392b','#2563eb','#d97706','#7c3aed','#0891b2','#db2777','#65a30d','#9a3412','#475569','#be123c','#0d9488'];
var cmpCat='all', cmpSel={{}};
function cmpTypeName(t){{return t==='call'?'個股選股型':(t==='macro'?'產業主題型':'大盤擇時型');}}
function renderPicks(){{
  // 「＋加入」下拉裡的可勾選清單（依類型篩選；已選的打勾）
  var box=document.getElementById('cmp-add-list'); if(!box) return; box.innerHTML='';
  WALL.forEach(function(w,i){{
    if(cmpCat!=='all' && w.type!==cmpCat) return;
    var on=cmpSel[w.name];
    var col=CMP_PAL[i%CMP_PAL.length];
    var el=document.createElement('div');
    el.className='cmp-opt'+(on?' on':'');
    el.innerHTML='<span class="dotc" style="background:'+col+'"></span><span class="cmp-opt-nm">'+w.name+'</span>'+(on?'<span class="cmp-opt-ck">✓</span>':'');
    el.onclick=function(){{cmpSel[w.name]=!cmpSel[w.name];renderPicks();drawCmp();}};
    box.appendChild(el);
  }});
}}
function toggleCmpAdd(e){{
  if(e)e.stopPropagation();
  var p=document.getElementById('cmp-add-panel');
  var open=p.classList.toggle('on');
  document.getElementById('cmp-add-btn').classList.toggle('on',open);
}}
document.addEventListener('click',function(e){{
  var w=document.querySelector('.cmp-add-wrap');
  var p=document.getElementById('cmp-add-panel');
  if(p&&p.classList.contains('on')&&w&&!w.contains(e.target)){{
    p.classList.remove('on');document.getElementById('cmp-add-btn').classList.remove('on');
  }}
}});
function cmpRemove(i){{ cmpSel[WALL[i].name]=false; renderPicks(); drawCmp(); }}
function cmpFilter(cf,btn){{
  cmpCat=cf;
  document.querySelectorAll('#cmp-seg button[data-cf]').forEach(function(b){{b.classList.toggle('on',b.dataset.cf===cf);}});
  renderPicks();
}}
function cmpAll(on){{
  WALL.forEach(function(w){{if(cmpCat==='all'||w.type===cmpCat)cmpSel[w.name]=on;}});
  renderPicks();drawCmp();
}}
function cmpReset(){{
  cmpSel={{}};
  var n=0; WALL.forEach(function(w){{if(w.type==='call'&&n<3){{cmpSel[w.name]=true;n++;}}}});
  renderPicks();drawCmp();
}}
var cmpTabActive='curve';
function setCmpTab(tab,btn){{
  cmpTabActive=tab;
  document.querySelectorAll('.cmp-tab').forEach(function(b){{b.classList.remove('on');}});
  btn.classList.add('on');
  var cc=document.getElementById('cmp-chart'),ec=document.getElementById('ev-chart');
  if(cc)cc.style.display=tab==='curve'?'':'none';
  if(ec)ec.style.display=tab==='event'?'':'none';
  drawCmp();
}}
function _t(d){{return new Date(d).getTime();}}
function drawCmp(){{
  var svg=document.getElementById('cmp-chart'); var W=800,H=300;
  var mL=46,mR=14,mT=14,mB=30;
  var sel=WALL.filter(function(w){{return cmpSel[w.name];}});
  var leg=document.getElementById('cmp-legend');
  if(!sel.length){{svg.innerHTML='<text x="400" y="150" text-anchor="middle" fill="#aab0b8" font-size="14">勾選上方分析師以畫圖</text>';leg.innerHTML='';return;}}
  // 真實時間範圍 + $ 範圍（含各自大盤線）
  var t0=1e18,t1=-1e18,lo=1e9,hi=-1e9;
  sel.forEach(function(w){{
    t0=Math.min(t0,_t(w.dates[0])); t1=Math.max(t1,_t(w.dates[w.dates.length-1]));
    w.curve.forEach(function(v){{if(v<lo)lo=v;if(v>hi)hi=v;}});
    w.mcurve.forEach(function(v){{if(v<lo)lo=v;if(v>hi)hi=v;}});
  }});
  lo=Math.min(lo,100); hi=Math.max(hi,100);
  var pa=(hi-lo)*0.08||10; lo-=pa; hi+=pa; var rng=hi-lo; var tr=(t1-t0)||1;
  var px0=mL,px1=W-mR,py0=mT,py1=H-mB;
  function X(t){{return px0+(px1-px0)*(t-t0)/tr;}}
  function Y(v){{return py1-(py1-py0)*(v-lo)/rng;}}
  function poly(dates,vals,col,w,dash){{
    var p=vals.map(function(v,j){{return X(_t(dates[j])).toFixed(1)+','+Y(v).toFixed(1);}}).join(' ');
    return '<polyline points="'+p+'" fill="none" stroke="'+col+'" stroke-width="'+w+'"'+(dash?' stroke-dasharray="5 4"':'')+'/>';
  }}
  var s='';
  // Y 軸刻度
  for(var k=0;k<=4;k++){{
    var val=lo+rng*k/4; var y=Y(val);
    s+='<line x1="'+px0+'" y1="'+y.toFixed(1)+'" x2="'+px1+'" y2="'+y.toFixed(1)+'" stroke="#f0f1f4"/>';
    s+='<text x="'+(px0-6)+'" y="'+(y+3).toFixed(1)+'" text-anchor="end" fill="#9aa0a8" font-size="11">$'+Math.round(val)+'</text>';
  }}
  s+='<line x1="'+px0+'" y1="'+Y(100).toFixed(1)+'" x2="'+px1+'" y2="'+Y(100).toFixed(1)+'" stroke="#c9ccd1" stroke-dasharray="4 4"/>';
  // X 軸：每年一刻度
  var y0=new Date(t0).getFullYear(), y1=new Date(t1).getFullYear();
  for(var yr=y0; yr<=y1; yr++){{
    var tx=_t(yr+'-01-01'); if(tx<t0||tx>t1) continue; var x=X(tx);
    s+='<line x1="'+x.toFixed(1)+'" y1="'+py0+'" x2="'+x.toFixed(1)+'" y2="'+py1+'" stroke="#f6f6f8"/>';
    s+='<text x="'+x.toFixed(1)+'" y="'+(H-9)+'" text-anchor="middle" fill="#9aa0a8" font-size="11">'+yr+'</text>';
  }}
  s+='<line x1="'+px0+'" y1="'+py1+'" x2="'+px1+'" y2="'+py1+'" stroke="#d2d6dc"/>';
  // 大盤線：每位各畫自己的綜合大盤（同色虛線），不去重——因為各人回測起點不同、
  // 基準經 $100 正規化後彼此不同，用單一線代表全部會誤導。
  sel.forEach(function(w){{
    var i=WALL.indexOf(w),col=CMP_PAL[i%CMP_PAL.length];
    s+=poly(w.dates,w.mcurve,col,1.3,true);
  }});
  // 分析師線：砍掉開頭那段「空手＝$100 平」的前導線，從他第一次真正出手才畫
  sel.forEach(function(w){{
    var i=WALL.indexOf(w);
    var st=0; while(st<w.curve.length-1 && Math.abs(w.curve[st]-100)<0.01) st++;
    st=Math.max(0,st-1); // 保留一個 $100 起錨點
    s+=poly(w.dates.slice(st),w.curve.slice(st),CMP_PAL[i%CMP_PAL.length],2,false);
  }});
  svg.innerHTML=s;
  // 共用 legend + note（依 tab 切換內容）
  var noteEl=document.getElementById('cmp-note');
  if(cmpTabActive==='event'){{
    drawEvent();
    // event legend
    var evSel=sel.filter(function(w){{return EVENT[w.name];}});
    var lg2=evSel.map(function(w){{
      var i=WALL.indexOf(w),col=CMP_PAL[i%CMP_PAL.length],ev=EVENT[w.name];
      var pre=(ev.path[ev.days.indexOf(0)]-ev.path[0]).toFixed(1);
      return '<div class="cmp-lg-name"><span class="dotc" style="background:'+col+'"></span>'+w.name+'</div><span class="cmp-lg-v">+'+pre+'%</span><span class="cmp-lg-a">喊買前</span><button class="cmp-lg-x" onclick="cmpRemove('+i+')" aria-label="移除">✕</button>';
    }});
    leg.innerHTML=lg2.join('');
    if(noteEl)noteEl.innerHTML='怎麼看這張圖 <span class="info" data-tip="把每筆看多 call 對齊到喊買日（第 0 天），看喊買前後股價平均走勢（喊買日＝$100）。喊買前一路往上＝他在追漲；喊買後走平＝你買到尾巴。僅個股選股型與股癌適用。">i</span>';
  }} else {{
    // curve legend（帶 α tag）
    var lg1=sel.map(function(w){{
      var i=WALL.indexOf(w),col=CMP_PAL[i%CMP_PAL.length];
      // 各人自己的綜合大盤終值，放進同一列（實線=跟他、虛線=他的綜合大盤）
      var aCell='<span class="cmp-lg-a">大盤 $'+Math.round(w.mkt)+'</span>';
      return '<div class="cmp-lg-name"><span class="dotc" style="background:'+col+'"></span>'+w.name+'</div><span class="cmp-lg-v">$'+Math.round(w.follow)+'</span>'+aCell+'<button class="cmp-lg-x" onclick="cmpRemove('+i+')" aria-label="移除">✕</button>';
    }});
    leg.innerHTML=lg1.join('');
    if(noteEl)noteEl.innerHTML='怎麼看這張圖 <span class="info" data-tip="每人兩條同色線：實線＝$100 跟他（看多）的成長，虛線＝他自己的『綜合大盤』（逐筆配對各自基準、加權累積，非單一指數）。各人回測起點不同、都從 $100 起算，所以每人有各自的大盤線，不共用一條；終值不能跨人比。">i</span>';
  }}
}}

function drawEvent(){{
  var svg=document.getElementById('ev-chart'); if(!svg) return;
  var sel=WALL.filter(function(w){{return cmpSel[w.name] && EVENT[w.name];}});
  if(!sel.length){{svg.innerHTML='<text x="400" y="140" text-anchor="middle" fill="#aab0b8" font-size="14">勾選個股選股型或股癌以畫圖</text>';return;}}
  var W=800,H=280,mL=46,mR=14,mT=14,mB=28;
  var lo=1e9,hi=-1e9;
  sel.forEach(function(w){{EVENT[w.name].path.forEach(function(v){{if(v<lo)lo=v;if(v>hi)hi=v;}});}});
  lo=Math.min(lo,100);hi=Math.max(hi,100);
  var pa=(hi-lo)*0.1||5; lo-=pa; hi+=pa; var rng=hi-lo;
  var days=EVENT[sel[0].name].days, D0=days[0], D1=days[days.length-1], dr=D1-D0;
  var px0=mL,px1=W-mR,py0=mT,py1=H-mB;
  function X(d){{return px0+(px1-px0)*(d-D0)/dr;}}
  function Y(v){{return py1-(py1-py0)*(v-lo)/rng;}}
  var s='';
  for(var k=0;k<=4;k++){{var val=lo+rng*k/4;var y=Y(val);
    s+='<line x1="'+px0+'" y1="'+y.toFixed(1)+'" x2="'+px1+'" y2="'+y.toFixed(1)+'" stroke="#f0f1f4"/>';
    s+='<text x="'+(px0-6)+'" y="'+(y+3).toFixed(1)+'" text-anchor="end" fill="#9aa0a8" font-size="11">$'+Math.round(val)+'</text>';}}
  // 喊買日（第0天）紅線
  var x0=X(0);
  s+='<line x1="'+x0.toFixed(1)+'" y1="'+py0+'" x2="'+x0.toFixed(1)+'" y2="'+py1+'" stroke="#c0392b" stroke-dasharray="4 3" stroke-width="1.3"/>';
  s+='<text x="'+x0.toFixed(1)+'" y="'+(H-9)+'" text-anchor="middle" fill="#c0392b" font-size="11">喊買日</text>';
  s+='<text x="'+px0+'" y="'+(H-9)+'" text-anchor="start" fill="#9aa0a8" font-size="11">'+D0+'日</text>';
  s+='<text x="'+px1+'" y="'+(H-9)+'" text-anchor="end" fill="#9aa0a8" font-size="11">+'+D1+'日</text>';
  s+='<line x1="'+px0+'" y1="'+py1+'" x2="'+px1+'" y2="'+py1+'" stroke="#d2d6dc"/>';
  sel.forEach(function(w){{
    var i=WALL.indexOf(w); var col=CMP_PAL[i%CMP_PAL.length]; var ev=EVENT[w.name];
    var p=ev.path.map(function(v,j){{return X(ev.days[j]).toFixed(1)+','+Y(v).toFixed(1);}}).join(' ');
    s+='<polyline points="'+p+'" fill="none" stroke="'+col+'" stroke-width="2"/>';
  }});
  svg.innerHTML=s;
}}

// ── AI 問答功能 JS（多輪對話）──────────────────────────
var askHistory = [];  // [{{role:'user'/'assistant', content:str}}]

function askQuick(btn) {{
  document.getElementById('ask-input').value = btn.innerText;
  askAI();
}}

function _askEsc(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

async function askAI() {{
  var input = document.getElementById('ask-input');
  var q = input.value.trim();
  if(!q) return;

  var btn = document.getElementById('ask-btn');
  var log = document.getElementById('ask-log');
  var empty = document.getElementById('ask-empty');
  if(empty) empty.style.display = 'none';

  // 使用者這則泡泡
  var uTurn = document.createElement('div');
  uTurn.className = 'ask-turn user';
  uTurn.innerHTML = '<div class="ask-q">' + _askEsc(q) + '</div>';
  log.appendChild(uTurn);

  // AI 回覆佔位（loading）
  var bTurn = document.createElement('div');
  bTurn.className = 'ask-turn bot';
  bTurn.innerHTML = '<div class="ask-loading">正在搜尋與計算，請稍候<span class="ask-dots"><span></span><span></span><span></span></span></div>';
  log.appendChild(bTurn);
  bTurn.scrollIntoView({{behavior:'smooth', block:'end'}});

  input.value = '';
  btn.disabled = true;

  // 送出前先固定這次的歷史（不含當前問題）
  var historyToSend = askHistory.slice();
  // 開著分析師卡且問題沒點名時，自動聚焦該人（泡泡顯示原句，送出才加前綴）
  var sendQ = q;
  if(_cardOpen && q.indexOf(_cardOpen.name) === -1) sendQ = '關於 ' + _cardOpen.name + '：' + q;

  try {{
    var res = await fetch('/api/ask', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{question: sendQ, history: historyToSend}})
    }});
    if (res.status === 404 || res.status === 405 || res.status === 501) {{
      throw new Error('__OFFLINE__');
    }}
    if (!res.ok) {{
      throw new Error('HTTP 錯誤：' + res.status);
    }}
    var data = await res.json();
    if (data.error) {{
      throw new Error(data.error);
    }}
    bTurn.innerHTML = '<div class="ask-card">' + renderAskMarkdown(data.answer) + '</div>';
    // 記進對話歷史，供下一次追問帶上文脈
    askHistory.push({{role:'user', content:sendQ}});
    askHistory.push({{role:'assistant', content:data.answer}});
    // 只保留最近 6 則往返，避免 payload 過大
    if(askHistory.length > 12) askHistory = askHistory.slice(-12);
  }} catch (e) {{
    if (e.message === '__OFFLINE__' || e.message.indexOf('Failed to fetch') !== -1 || e.message.indexOf('NetworkError') !== -1 || e.message.indexOf('Failed to execute') !== -1) {{
      bTurn.innerHTML = '<div class="ask-offline"><b>⚠️ 無法連線到後端服務</b><br>AI 問答需要啟動 FastAPI 後端（<code>python server.py</code>）才能使用；目前這份是純靜態頁面，此功能離線中。其他分析頁面可照常使用。</div>';
    }} else {{
      bTurn.innerHTML = '<div class="ask-error">❌ 查詢失敗：' + e.message + '</div>';
    }}
  }} finally {{
    btn.disabled = false;
    input.focus();
    bTurn.scrollIntoView({{behavior:'smooth', block:'end'}});
  }}
}}

function renderAskMarkdown(text) {{
  if(!text) return '';
  var html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  
  html = html.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
  
  var lines = html.split('\\n');
  var inTable = false;
  var tableHtml = '';
  var newLines = [];
  
  for (var i = 0; i < lines.length; i++) {{
    var line = lines[i].trim();
    if (line.startsWith('|')) {{
      if (!inTable) {{
        inTable = true;
        tableHtml = '<table>';
      }}
      var cols = line.split('|').map(function(c) {{ return c.trim(); }});
      cols = cols.slice(1, cols.length - 1);
      
      if (line.match(/^\\|[\\s-|-]*\\|$/)) {{
        continue;
      }}
      
      if (tableHtml === '<table>') {{
        tableHtml += '<thead><tr>' + cols.map(function(c) {{ return '<th>' + c + '</th>'; }}).join('') + '</tr></thead><tbody>';
      }} else {{
        tableHtml += '<tr>' + cols.map(function(c) {{ return '<td>' + c + '</td>'; }}).join('') + '</tr>';
      }}
    }} else {{
      if (inTable) {{
        inTable = false;
        tableHtml += '</tbody></table>';
        newLines.push(tableHtml);
        tableHtml = '';
      }}
      newLines.push(lines[i]);
    }}
  }}
  if (inTable) {{
    tableHtml += '</tbody></table>';
    newLines.push(tableHtml);
  }}
  
  html = newLines.join('\\n');
  
  var paragraphs = html.split('\\n\\n');
  return paragraphs.map(function(p) {{
    var pTrim = p.trim();
    if(!pTrim) return '';
    
    if(pTrim.startsWith('- ') || pTrim.startsWith('* ')) {{
      var items = pTrim.split(/\\n[-*] /);
      return '<ul>' + items.map(function(item) {{
        return '<li>' + item.replace(/^[-*] /, '').replace(/\\n/g, '<br>') + '</li>';
      }}).join('') + '</ul>';
    }}
    
    if(pTrim.match(/^\\d+\\.\\s/)) {{
      var items = pTrim.split(/\\n\\d+\\.\\s/);
      return '<ol>' + items.map(function(item) {{
        return '<li>' + item.replace(/^\\d+\\.\\s/, '').replace(/\\n/g, '<br>') + '</li>';
      }}).join('') + '</ol>';
    }}
    
    if(pTrim.startsWith('### ')) {{
      return '<h3>' + pTrim.substring(4) + '</h3>';
    }}
    
    if(pTrim.startsWith('&gt; ')) {{
      return '<blockquote>' + pTrim.replace(/^&gt; /gm, '') + '</blockquote>';
    }}
    
    if(pTrim.startsWith('```')) {{
      return '<pre><code>' + pTrim.replace(/```[a-zA-Z]*/g, '').trim() + '</code></pre>';
    }}
    
    return '<p>' + pTrim.replace(/\\n/g, '<br>') + '</p>';
  }}).join('');
}}

(function(){{ // 預設勾個股選股型前 3 名（依績效，WALL 已依出現序）
  var n=0; WALL.forEach(function(w){{if(w.type==='call'&&n<3){{cmpSel[w.name]=true;n++;}}}});
  renderPicks(); drawCmp();
}})();
// 初始依績效排序
(function(){{
  var g=document.getElementById('grid');
  [].slice.call(g.querySelectorAll('.ncard')).sort(function(a,b){{
    return parseFloat(b.dataset.excess)-parseFloat(a.dataset.excess);
  }}).forEach(function(c){{g.appendChild(c)}});
}})();
</script>
</body></html>"""

open("index.html", "w", encoding="utf-8").write(html)
print(f"✅ index.html 生成完畢（{len(html)//1024} KB）")
