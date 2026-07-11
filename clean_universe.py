"""清理 stock_universe.csv 的雜訊，輸出乾淨的 universe。

兩類雜訊：
  1. 普通詞誤匹配：「數字」「世界」「大量」等日常用語
  2. 子字串衝突：「聯發」是「聯發科」的子字串，計數被吃掉

輸出：
  stock_universe_clean.csv — 乾淨的 universe
"""
from __future__ import annotations
import pandas as pd
import re

# --------------------------------------------------------------------------
# 1. 常見普通詞黑名單（這些詞作為股票關鍵字會大量誤匹配）
# --------------------------------------------------------------------------
COMMON_WORD_BLACKLIST = {
    # 數量/程度詞
    "數字", "大量", "有量", "無量", "少量",
    # 地理/通用詞
    "大陸", "全台", "全國", "世界", "亞洲", "台灣",
    # 形容詞/動詞
    "互動", "安心", "無敵", "大成", "正新", "新光", "光明",
    "中視", "中天", "三星", "大同", "大統",
    # 太短且模糊（2字但是普通詞）
    "統一", "聯合", "合作", "永豐", "永信",
    # 其他常見誤匹配
    "波若", "全新", "數位", "奇美", "旭日",
    # 補充排除
    "幸福", "信大",  # 名稱像普通詞
    "波若威",        # 波若誤匹配
    "天剛",          # 「今天剛剛」被誤切
}

# --------------------------------------------------------------------------
# 2. 手動指定「子字串衝突」的保留/排除規則
#    key=被排除的(短名), value=正確的(長名)
# --------------------------------------------------------------------------
SUBSTRING_OVERRIDE = {
    "聯發": "聯發科",      # 1459/2756 → 是 2454 聯發科的誤切
    "聯發國際": "聯發科",  # 2756 → 同上
    "南亞": "南亞科",      # 1303 → 多半是講 2408 南亞科
    "台光": "台光電",      # 1601 → 多半是講 2383 台光電
    "冠軍": None,          # 冠軍磁磚(1806)很少被投顧講，應排除
    "大陸": None,          # 普通詞
    "三星": None,          # 韓國三星 or 5007三星，太模糊
    "聯鈞": None,          # 小型股，3450，很可能是「聯」的誤切
}

# --------------------------------------------------------------------------
# 3. 子字串衝突自動偵測
# --------------------------------------------------------------------------

def detect_substring_conflicts(df: pd.DataFrame) -> list[dict]:
    """找出 A 的名稱是 B 的名稱子字串，且 B 的 video_count 遠多於 A 的情況。"""
    conflicts = []
    names = df[["stock_id", "name", "video_count"]].values.tolist()

    for i, (sid_a, name_a, cnt_a) in enumerate(names):
        if not name_a or len(name_a) < 2:
            continue
        for sid_b, name_b, cnt_b in names:
            if sid_a == sid_b or not name_b:
                continue
            # A 的名稱是 B 名稱的子字串（且 B 出現次數 > A 的 2 倍）
            if name_a in name_b and cnt_b > cnt_a * 2:
                conflicts.append({
                    "keep_out": sid_a, "keep_out_name": name_a, "keep_out_count": cnt_a,
                    "conflict_with": sid_b, "conflict_name": name_b, "conflict_count": cnt_b,
                })
                break
    return conflicts


# --------------------------------------------------------------------------
# 主程式
# --------------------------------------------------------------------------

def main():
    df = pd.read_csv("stock_universe.csv", dtype={"stock_id": str})
    print(f"原始 universe：{len(df)} 支")

    exclude_ids = set()
    reasons = {}

    # Step 1：黑名單詞過濾
    for _, row in df.iterrows():
        name = str(row["name"])
        if name in COMMON_WORD_BLACKLIST:
            exclude_ids.add(row["stock_id"])
            reasons[row["stock_id"]] = f"普通詞黑名單：{name}"

    print(f"  黑名單排除：{len(exclude_ids)} 支")

    # Step 2：手動子字串 override
    name_to_id = dict(zip(df["name"], df["stock_id"]))
    for short_name, correct_name in SUBSTRING_OVERRIDE.items():
        sid = name_to_id.get(short_name)
        if sid:
            exclude_ids.add(sid)
            reasons[sid] = f"子字串衝突（應為 {correct_name}）" if correct_name else "模糊/排除"

    # Step 3：自動偵測子字串衝突（僅對 video_count >= 10 的才做）
    df_check = df[df["video_count"] >= 10].copy()
    conflicts = detect_substring_conflicts(df_check)
    auto_excluded = 0
    for c in conflicts:
        if c["keep_out"] not in exclude_ids:
            exclude_ids.add(c["keep_out"])
            reasons[c["keep_out"]] = (
                f"自動子字串衝突：'{c['keep_out_name']}'⊂'{c['conflict_name']}' "
                f"({c['keep_out_count']} vs {c['conflict_count']})"
            )
            auto_excluded += 1

    print(f"  自動子字串排除：{auto_excluded} 支")

    # Step 4：排除 ETF（stock_id 開頭 0 或 6 碼以上）
    etf_ids = df[df["stock_id"].str.match(r"^0\d{3}$")]["stock_id"].tolist()
    for sid in etf_ids:
        if sid not in exclude_ids:
            exclude_ids.add(sid)
            reasons[sid] = "ETF 排除"

    # Step 5：最低品質門檻（至少 3 個頻道、5 個週次）
    low_quality = df[
        (df["n_channels"] < 3) | (df["n_weeks"] < 5)
    ]["stock_id"].tolist()
    for sid in low_quality:
        if sid not in exclude_ids:
            exclude_ids.add(sid)
            reasons[sid] = "覆蓋不足（頻道<3 或 週次<5）"

    print(f"  覆蓋不足排除：{len(low_quality)} 支（含已排除）")

    # 輸出清理後的 universe
    df_clean = df[~df["stock_id"].isin(exclude_ids)].copy()
    df_clean = df_clean.sort_values("video_count", ascending=False).reset_index(drop=True)

    print(f"\n清理後 universe：{len(df_clean)} 支")
    print(f"\n影片數 ≥ 50 的股票：{(df_clean['video_count'] >= 50).sum()} 支")
    print(f"影片數 ≥ 20 的股票：{(df_clean['video_count'] >= 20).sum()} 支")

    print(f"\nTop 60：")
    print(df_clean.head(60).to_string(index=False))

    # 印出被排除的清單供確認
    df_excluded = df[df["stock_id"].isin(exclude_ids)].copy()
    df_excluded["reason"] = df_excluded["stock_id"].map(reasons)
    df_excluded = df_excluded.sort_values("video_count", ascending=False)

    print(f"\n=== 被排除的股票（前 30 高頻）===")
    print(df_excluded[["stock_id", "name", "video_count", "reason"]].head(30).to_string(index=False))

    df_clean.to_csv("stock_universe_clean.csv", index=False, encoding="utf-8-sig")
    df_excluded.to_csv("stock_universe_excluded.csv", index=False, encoding="utf-8-sig")
    print(f"\n已存：stock_universe_clean.csv / stock_universe_excluded.csv")


if __name__ == "__main__":
    main()
