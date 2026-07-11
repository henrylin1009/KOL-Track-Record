"""Survivorship 測試：cov=0×殘差突破 edge 在「曾被提過」vs「從未被提過」股票

若 edge 只存在於「曾被提過」股票（=未來會紅的 survivor）→ 之前 +1.67% 有 survivorship 灌水
若「從未被提過」股票也有同樣 edge → edge 是普遍真實的，與 survivorship 無關

用法：python survivorship_test.py [HOLD]
"""
from __future__ import annotations
import sys, pickle, sqlite3
import numpy as np
import pandas as pd
from scipy import stats
import config

LOOKBACK = 20
HOLD     = int(sys.argv[1]) if len(sys.argv) > 1 else 20
LIQ_MIN  = float(sys.argv[2]) * 1e6 if len(sys.argv) > 2 else 0.0  # 最低日成交額(百萬元)
COV_WIN  = 20
BETA_WIN = 120
COST     = 0.006
OOS      = pd.Timestamp("2025-01-01")
CACHE    = "full_price_cache.pkl"


def load_mention_dates():
    conn = sqlite3.connect(config.STOCK_DB_PATH)
    rows = conn.execute("""
        SELECT s.stock_id, v.upload_date FROM stock_sentiment s
        JOIN video_log v ON s.video_id=v.video_id
        WHERE s.stock_id!='__none__' AND s.mention_count>0 AND v.upload_date!=''
    """).fetchall()
    conn.close()
    by = {}
    for sid, d in rows:
        ts = pd.to_datetime(d, format="%Y%m%d", errors="coerce")
        if pd.notna(ts): by.setdefault(sid, []).append(ts)
    return {k: np.array(sorted(v), dtype="datetime64[ns]") for k, v in by.items()}


def main():
    data = pickle.load(open(CACHE, "rb"))
    taiex, prices = data["taiex"], data["prices"]
    dvol = data.get("dollar_vol", {})
    mkt_ret = taiex.pct_change()
    mkt_var = mkt_ret.rolling(BETA_WIN).var()
    mentions = load_mention_dates()
    ever_mentioned = set(mentions.keys())

    # 流動性篩選：兩組都只留日成交額 >= LIQ_MIN 的股票
    if LIQ_MIN > 0:
        prices = {s: c for s, c in prices.items() if dvol.get(s, 0) >= LIQ_MIN}
    print(f"流動性門檻：日成交額 >= {LIQ_MIN/1e6:.0f}M 元")
    print(f"篩後宇宙 {len(prices)} 支｜曾被提過 {len(ever_mentioned & set(prices))} 支｜"
          f"從未被提過 {len(set(prices) - ever_mentioned)} 支\n")

    recs = []
    for sid, close in prices.items():
        close = close[~close.index.duplicated()].sort_index()
        if len(close) < BETA_WIN + LOOKBACK + HOLD + 5: continue
        ret = close.pct_change()
        m = mkt_ret.reindex(ret.index)
        beta = (ret.rolling(BETA_WIN).cov(m) / mkt_var.reindex(ret.index)).clip(-3, 3)
        resid = (ret - beta * m).replace([np.inf, -np.inf], np.nan).where(lambda s: s.abs() < 0.5)
        cr = resid.cumsum()
        md = mentions.get(sid, np.array([], dtype="datetime64[ns]"))
        ever = sid in ever_mentioned
        td = close.index
        for fri in close.resample("W-FRI").last().index:
            pos = td.searchsorted(fri, side="right") - 1
            if pos < BETA_WIN + LOOKBACK or pos + HOLD >= len(td): continue
            if np.isnan(cr.iloc[pos]): continue
            cr_win = cr.iloc[pos - LOOKBACK + 1: pos + 1]
            if cr_win.isna().any(): continue
            breakout = cr.iloc[pos] >= cr_win.max() - 1e-12
            if not breakout: continue
            t = td[pos]; lo = td[pos - COV_WIN + 1]
            cov = int(((md >= np.datetime64(lo)) & (md <= np.datetime64(t))).sum()) if len(md) else 0
            if cov != 0: continue        # 只看 cov=0 突破
            fwd = resid.reindex(td[pos + 1: pos + HOLD + 1]).sum()
            if np.isnan(fwd): continue
            recs.append((sid, t, ever, fwd))

    df = pd.DataFrame(recs, columns=["sid", "date", "ever", "fwd"])

    def rep(label, sub):
        if len(sub) < 20: print(f"{label:<34} N={len(sub):>5} 樣本不足"); return
        t, _ = stats.ttest_1samp(sub["fwd"], 0.0)
        print(f"{label:<34} N={len(sub):>6}  毛{sub['fwd'].mean()*100:+.2f}%  "
              f"t={t:+.2f}{'★' if abs(t)>2 else ' '}  淨{(sub['fwd'].mean()-COST)*100:+.2f}%")

    print("=" * 72)
    print(f"cov=0 × 殘差突破（持有{HOLD}日）— survivorship 對照")
    print("=" * 72)
    rep("全宇宙", df)
    rep("  曾被提過 (survivor)", df[df.ever])
    rep("  從未被提過 (clean)", df[~df.ever])
    if (df.ever.sum() > 20) and ((~df.ever).sum() > 20):
        t, _ = stats.ttest_ind(df[df.ever]["fwd"], df[~df.ever]["fwd"], equal_var=False)
        diff = (df[df.ever]["fwd"].mean() - df[~df.ever]["fwd"].mean()) * 100
        print(f"\n  survivor − clean 差 = {diff:+.2f}%  t={t:+.2f}"
              f"{'  ★ survivorship 有灌水' if abs(t)>2 else '  (無顯著灌水)'}")

    print("\n── 從未被提過股票的 OOS 穩健性 ──")
    clean = df[~df.ever]
    rep("  clean In-Sample 22-24", clean[clean.date < OOS])
    rep("  clean Out-of-Sample 25+", clean[clean.date >= OOS])


if __name__ == "__main__":
    main()
