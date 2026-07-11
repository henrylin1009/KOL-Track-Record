"""
scorecard.py — 分析師「彙總戰績」單一真相源。

卡片(第一/二/三部分)顯示的頭條數字都由 calendar_multi.json 算好；
本檔把那批彙總欄位原封不動讀出來，給：
  ① generate_site.py（建站時算第三部分體檢表）
  ② ask_combined.py 的 get_scorecard 工具（讓 AI 問答讀得到卡片數字）

★ 誠實界線：所有統計都是引擎預先算好的，LLM 一律不碰計算。
"""
from __future__ import annotations
import json


# ── 第三部分體檢表（原 generate_site._compute_health，抽出共用）─────────
def compute_health(call_results, avail_horizons):
    """Per-horizon health check stats from call_results.
    Handles both byh[h] nested (股票分析師) and flat (大盤擇時型/is_mb) structures."""
    is_flat = any(c.get('hit') in ('hit', 'miss') for c in call_results)

    def _get(c, h, field):
        """Unified field accessor for both nested/flat structures."""
        if is_flat:
            return c.get(field)
        return (c.get('byh') or {}).get(h, {}).get(field)

    def _settled(h):
        if is_flat:
            return [c for c in call_results if c.get('hit') in ('hit', 'miss')]
        return [c for c in call_results
                if h in (c.get('byh') or {})
                and (c['byh'][h] or {}).get('hit') in ('hit', 'miss')]

    out = {}
    _cache = {}  # for flat: reuse same result across horizons
    for h in avail_horizons:
        if is_flat and _cache:
            out[h] = _cache.get('val')
            continue
        settled = _settled(h)
        n = len(settled)
        if n == 0:
            out[h] = None
            if is_flat: _cache['val'] = None
            continue
        excesses = [_get(c, h, 'excess') or 0 for c in settled]
        hits_c   = [c for c in settled if _get(c, h, 'hit') == 'hit']
        miss_c   = [c for c in settled if _get(c, h, 'hit') == 'miss']
        # 1. 贏過亂猜
        beat = round(len(hits_c) / n * 100, 1)
        # 2. 集中度：前 20% 喊單貢獻多少正超額
        total_pos = sum(e for e in excesses if e > 0)
        top20_n = max(1, int(n * 0.2))
        top20_pos = sum(e for e in sorted(excesses, reverse=True)[:top20_n] if e > 0)
        conc = round(top20_pos / total_pos * 100) if total_pos > 0 else None
        # 3. 贏/輸幅度
        avg_win  = round(sum(_get(c,h,'excess') or 0 for c in hits_c) / len(hits_c), 1) if hits_c else None
        avg_loss = round(sum(_get(c,h,'excess') or 0 for c in miss_c) / len(miss_c), 1) if miss_c else None
        # 4. 滾動：平分 4 段
        s = sorted(settled, key=lambda c: c.get('date', ''))
        chunk = max(1, n // 4)
        rolling = []
        for i in range(0, n, chunk):
            seg = s[i:i + chunk]
            if not seg: continue
            r = round(sum(1 for c in seg if _get(c,h,'hit') == 'hit') / len(seg) * 100, 1)
            rolling.append({"label": seg[0].get('date', '')[:7], "rate": r})
        # 5. 神單/雷單
        ranked = sorted(settled, key=lambda c: _get(c, h, 'excess') or 0, reverse=True)
        def _fmt(c, _h=h):
            e = _get(c, _h, 'excess') or 0
            t = c.get('summary', '?')
            # 大盤擇時型 summary 很長，截斷到 20 字（hover 用 full 顯示完整）
            if is_flat and len(t) > 20: t = t[:20] + '…'
            return {"t": t, "full": c.get('full', c.get('summary', '?')), "e": round(e, 1),
                    "d": c.get('date', '?')[:10], "dir": c.get('dir', '')}
        val = {"n": n, "beat": beat, "conc": conc,
               "win": avg_win, "loss": avg_loss, "rolling": rolling,
               "top3": [_fmt(c) for c in ranked[:3]],
               "bot3": [_fmt(c) for c in ranked[-3:]]}
        out[h] = val
        if is_flat: _cache['val'] = val
    return out


# ── AI 問答工具：讀卡片彙總 ────────────────────────────────────────
_CM: dict | None = None
_VALID_HOLD = ("5", "20", "60", "120", "250")


def _load_cm() -> dict:
    global _CM
    if _CM is None:
        _CM = json.load(open("calendar_multi.json", encoding="utf-8"))
    return _CM


def _resolve(name: str, an: dict) -> str | None:
    if name in an:
        return name
    # 容忍 AI 傳「股癌」而非「股癌（謝孟恭）」等
    hits = [k for k in an if name in k or k in name]
    return hits[0] if len(hits) == 1 else None


def get_scorecard(analyst: str, hold: int = 20) -> dict:
    """回傳某分析師的『卡片彙總戰績』——與網站個人卡三部分同源、引擎預先算好。

    參數：
      analyst  分析師姓名（需在 list_analysts() 內）
      hold     持有天數（5/20/60/120/250 之一，預設 20）

    回傳（皆引擎算，可直接朗讀）：
      strategy（第一部分）：$100 跟他終值 / 買大盤終值 / 最大回撤 /
                            年化超額 + t + p 值 + 95% CI + FDR 顯著 + 判決句
      direction（第二部分）：贏大盤率 / 做多/看空命中筆數 / 有賺沒 / 方向命中率
      skill（第三部分）：贏過亂猜 / 集中度 / 贏輸幅度 / 每筆期望 /
                        近況趨勢 / 神單 top3 / 雷單 bot3
    """
    cm = _load_cm()
    an = cm.get("analysts", {})
    key = _resolve(analyst, an)
    if key is None:
        return {"found": False, "error": f"查無此分析師：{analyst}",
                "hint": "請用 list_analysts 內的精確姓名"}

    h = str(hold)
    if h not in _VALID_HOLD:
        return {"found": False, "error": f"hold 需為 {_VALID_HOLD} 之一，收到 {hold}"}

    b = an[key]
    hz = (b.get("horizons") or {}).get(h)
    if not hz:
        return {"found": False, "error": f"{key} 無 {h} 日資料"}

    # 判決句（同一把尺，非 AI 編）
    from verdict_rules import verdict as _verdict
    verdict_str = _verdict(b)

    # 第三部分體檢表
    hd = (compute_health(b.get("call_results") or [], [h]) or {}).get(h) or {}
    # 每筆期望：命中率×贏幅 +（1−命中率）×輸幅（與卡片 row3b 同式）
    expectancy = None
    if hd.get("win") is not None and hd.get("beat") is not None:
        p = hd["beat"] / 100
        expectancy = round(p * hd["win"] + (1 - p) * (hd.get("loss") or 0), 1)

    strategy = {
        "follow_end_usd": hz.get("follow_end"),
        "market_buyhold_end_usd": hz.get("mkt_end"),
        "max_drawdown_pct": hz.get("max_drawdown"),
        "excess_ann_pct": hz.get("excess_ann"),
        "t": hz.get("t"),
        "p_value": hz.get("p"),
        "ci95_pct": [hz.get("ci_lo"), hz.get("ci_hi")],
        "n_weeks": hz.get("n_weeks"),
        "fdr_significant": hz.get("fdr_sig"),
        "raw_significant": hz.get("raw_sig"),
        "verdict": verdict_str,
    }
    direction = {
        "beat_market_rate_pct": hz.get("beat_mkt"),      # 贏大盤率
        "profit_rate_pct": hz.get("hit_rate"),           # 有賺沒
        "hit_counts": hz.get("hc"),                      # {long/short:{hit,miss,pend}}
        "direction_hit_rate_pct": b.get("direction_hit_rate"),
        "bull_dir_hit_pct": b.get("bull_dir_hit"),
        "bear_dir_hit_pct": b.get("bear_dir_hit"),
    }
    skill = {
        "beat_coinflip_pct": hd.get("beat"),             # 贏過亂猜（基準 50%）
        "concentration_pct": hd.get("conc"),             # 前20%喊單佔正超額%
        "avg_win_pct": hd.get("win"),
        "avg_loss_pct": hd.get("loss"),
        "expectancy_pct": expectancy,                    # 每筆期望
        "rolling_hit_rates": hd.get("rolling"),          # 近況趨勢
        "best_trades": hd.get("top3"),                   # 神單
        "worst_trades": hd.get("bot3"),                  # 雷單
        "n_settled": hd.get("n"),
    }
    return {"found": True, "analyst": key, "market": b.get("market"),
            "label": b.get("label"), "hold": hold,
            "is_market_bet": b.get("is_market_bet", False),
            "strategy": strategy, "direction": direction, "skill": skill,
            "note": "所有數字皆由引擎預先算好（calendar_multi.json），非 AI 計算。"}


if __name__ == "__main__":
    import sys
    who = sys.argv[1] if len(sys.argv) > 1 else "股癌（謝孟恭）"
    print(json.dumps(get_scorecard(who, 20), ensure_ascii=False, indent=1))
