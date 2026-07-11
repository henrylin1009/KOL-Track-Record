"""
regression_test.py — 一鍵回歸測試，防止改動意外污染既有結果

比對 calendar_multi.json 每位分析師的 headline 數值與鎖定基準 baseline_lock.json。
任何超過容差的位移 → 報錯列出，逼你確認是「故意修正」還是「意外污染」。

用法：
  python regression_test.py            # 比對；不一致回傳 exit code 1
  python regression_test.py --lock     # 把現況鎖為新基準（故意修正後才用）
"""
from __future__ import annotations
import json, sys

CUR = "calendar_multi.json"
LOCK = "baseline_lock.json"
TOL = 0.3   # 容差（百分點 / %）；scale 窗等微小差異允許

# 每位鎖定的 headline 欄位（20日代表 + 方向命中率）
FIELDS = ["excess_ann", "follow_end", "mkt_end", "hit_rate", "beat_mkt", "max_drawdown"]


def snapshot(path):
    d = json.load(open(path, encoding="utf-8"))["analysts"]
    snap = {}
    for name, a in d.items():
        rec = {}
        h20 = a.get("horizons", {}).get("20")
        if h20:
            for f in FIELDS:
                if h20.get(f) is not None:
                    rec[f] = h20[f]
        if a.get("direction_hit_rate") is not None:
            rec["direction_hit_rate"] = a["direction_hit_rate"]
        snap[name] = rec
    return snap


def lock():
    json.dump(snapshot(CUR), open(LOCK, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"✅ 已鎖定基準 → {LOCK}（{len(snapshot(CUR))} 位）")


def test():
    try:
        base = json.load(open(LOCK, encoding="utf-8"))
    except FileNotFoundError:
        print("❌ 無基準檔，先跑 --lock"); return 1
    cur = snapshot(CUR)
    fails = []
    for name, brec in base.items():
        if name not in cur:
            fails.append(f"  ✗ {name}：基準有、現況消失"); continue
        for f, bv in brec.items():
            cv = cur[name].get(f)
            if cv is None:
                fails.append(f"  ✗ {name}.{f}：消失"); continue
            if abs(cv - bv) > TOL:
                fails.append(f"  ✗ {name}.{f}：{bv} → {cv}（差 {cv-bv:+.1f}）")
    new = [n for n in cur if n not in base]
    if new:
        print(f"ℹ️ 新增分析師（不算失敗）：{', '.join(new)}")
    if fails:
        print(f"❌ 回歸失敗，{len(fails)} 處位移超過容差 ±{TOL}：")
        print("\n".join(fails))
        print("\n→ 若為故意修正，跑 `python regression_test.py --lock` 重鎖基準。")
        return 1
    print(f"✅ 回歸通過：{len(base)} 位 headline 數值與基準一致（容差 ±{TOL}）")
    return 0


if __name__ == "__main__":
    if "--lock" in sys.argv:
        lock()
    else:
        sys.exit(test())
