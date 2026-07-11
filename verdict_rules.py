"""
verdict_rules.py — 判決句「規則生成」（公正內建：同一張規則表套所有人）

取代手寫判決句。輸入一位分析師在 calendar_multi.json 的結算結果，
依固定規則表輸出一句判決。沒有任何針對個人的特例。

規則分兩大類（由 is_market_bet 決定）：
  賭大盤/資產（命理派）→ 看「方向命中率」對照擲銅板基準
  賭個股/產業（喊單/總經）→ 看「FDR 校正後是否顯著」

用法：
  from verdict_rules import verdict
  s = verdict(analyst_dict)   # analyst_dict = calendar_multi['analysts'][name]
"""
from __future__ import annotations

REP = "20"   # 代表天期（與引擎 REP_HOLD 一致）
MIN_SETTLED = 30   # 方向命中率「樣本足」門檻
MIN_WEEKS   = 10   # 超額/擇時檢定「樣本足」門檻（週）
SIG_T       = 2.0  # 統一顯著門檻：|t|<SIG_T 一律判定不能（同一把尺）


def verdict_excess(excess_ann, t, n_weeks, what="擇時 vs 買進持有",
                   pos="優於買進持有", neg="劣於買進持有") -> str:
    """統一「超額」判決句：先過樣本、再過顯著門檻，否則一律「判定不能」。
    與個股型的 FDR 顯著門檻同精神——不顯著就不宣稱勝負（不論命理派或喊單派）。
    what/pos/neg 讓「擇時」與「配置」共用同一把尺、只換措辭。"""
    if t is None or n_weeks is None or n_weeks < MIN_WEEKS:
        return f"{what}：樣本不足、判定不能（僅 {n_weeks or 0} 週）"
    if abs(t) < SIG_T:
        return f"{what}：判定不能（差異未達統計顯著，t={t:.2f}）"
    sign = "+" if (excess_ann or 0) > 0 else ""
    return f"{what}顯著{pos if (excess_ann or 0) > 0 else neg}（{sign}{excess_ann:.0f}%/年，t={t:.2f}）"


def _best_horizon(hz: dict):
    """挑代表天期（20日）；無則取任一。"""
    return hz.get(REP) or (next(iter(hz.values())) if hz else None)


def verdict_market_dir(rate, n: int) -> str:
    """賭大盤/資產的「單一方向」判決句（看漲腿／看跌腿／整體共用同一把尺）。
    與 verdict() 的 is_market_bet 分支用同一組門檻，供前端方向鈕連動。"""
    if rate is None or n == 0:
        return "此方向尚無已結算預言，無法評定方向準度"
    if n < MIN_SETTLED:
        return f"方向命中率 {rate:.0f}%（僅 {n} 條已結算，樣本不足、暫不定論）"
    if rate < 45:
        return f"方向預測準度 {rate:.0f}%，低於擲銅板（50%）"
    if rate <= 55:
        return f"方向準度 {rate:.0f}%，與擲銅板無異"
    return f"方向預測準度 {rate:.0f}%，高於擲銅板基準"


def verdict(a: dict) -> str:
    """依規則表生成判決句。a = 單一分析師結果 dict。"""
    hz = a.get("horizons", {})
    if not hz:
        return "資料不足，未納入評比"

    # ── 賭大盤/資產（命理派）：方向命中率 ＋ 擇時（同一顯著門檻）──
    if a.get("is_market_bet"):
        dir_s = verdict_market_dir(a.get("direction_hit_rate"),
                                   a.get("n_direction_settled", 0))
        rep = _best_horizon(hz)
        tim_s = verdict_excess(rep.get("excess_ann"), rep.get("t"),
                               rep.get("n_weeks")) if rep else ""
        parts = [dir_s] + ([tim_s] if tim_s else [])
        alc = a.get("allocation")   # 配置層（Brinson，多資產型才有）
        if alc:
            parts.append(verdict_excess(alc.get("excess_ann"), alc.get("t"),
                                        alc.get("n_weeks"), what="配置（挑對市場）",
                                        pos="加分", neg="扣分"))
        return "；".join(parts)

    # ── 賭個股/產業：看 FDR 校正後是否顯著 ──
    any_fdr = any(s.get("fdr_sig") for s in hz.values())
    any_raw = any(s.get("raw_sig") for s in hz.values())
    rep = _best_horizon(hz)
    ex = rep.get("excess_ann", 0) if rep else 0

    # 看空腿補述（若他有看空且大多看錯/看對）
    short_note = ""
    sh = rep.get("short_hit") if rep else None
    sn = rep.get("short_n_weeks") if rep else None
    if sh is not None and sn:
        if sh < 45:
            short_note = "；但他的看空大多看錯"
        elif sh > 55:
            short_note = "；他的看空也多半看對"

    if any_fdr:
        fdr_pos = any(s.get("fdr_sig") and s.get("excess_ann", 0) > 0 for s in hz.values())
        if fdr_pos:
            return "做多嚴謹校正後仍顯著優於大盤" + short_note
        return "嚴謹校正後顯著，但方向為負（顯著低於大盤）" + short_note
    if any_raw:
        return "做多原始檢定顯著，但多重比較校正（Romano-Wolf）後消失" + short_note
    return "與大盤無統計顯著差異（樣本下偵測不到 alpha）" + short_note


# 自測：對現有 4 人/類型印出判決
if __name__ == "__main__":
    import json
    d = json.load(open("calendar_multi.json", encoding="utf-8"))["analysts"]
    for name, a in d.items():
        print(f"{name:<16} | {verdict(a)}")
