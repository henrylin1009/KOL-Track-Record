"""
manage.py — 分析師管理 CLI（admin 面板後端也呼叫本檔，同一套邏輯）。

用法：
  python manage.py list             # 列出所有分析師（內建 + 動態）與資料狀態
  python manage.py refresh 名字      # 重抓逐字稿 + 重抽取 + 重建（限動態新增者）
  python manage.py remove 名字       # 從註冊表移除（軟移除：資料檔留在 data_cache）+ 重建
  python manage.py rebuild          # 引擎 → 建站 → 回歸驗證

界線：內建 13 位寫死在 analysts.py / config.TARGET_CHANNELS，list 會顯示但
refresh/remove 只作用於 add_analyst.py 動態註冊者（data_cache/analysts_registry.json）。
refresh 需要 audit/{名字}.json 裡的 channel_id（add_analyst 跑完自動就有）。
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).parent
REGISTRY = ROOT / "data_cache/analysts_registry.json"
AUDIT_DIR = ROOT / "audit"


def _load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {}


def roster() -> list[dict]:
    """全名單：內建（analysts.ANALYSTS + kol_registry）+ 動態註冊，附資料狀態。"""
    import analysts as ana
    dyn = _load_registry()
    cm_path = ROOT / "calendar_multi.json"
    cm_an = (json.loads(cm_path.read_text(encoding="utf-8")) if cm_path.exists() else {}).get("analysts", {})
    rows = []
    full = {**ana.kol_registry(), **ana.ANALYSTS}
    _lk_slug = {"gooaye": "gooaye", "dac": "dac", "wu": "wu"}   # 內建三位 cfg 沒 slug 欄
    for name, cfg in full.items():
        slug = cfg.get("slug") or _lk_slug.get(cfg.get("loader_key"), "")
        tpath = ROOT / f"data_cache/{slug}_transcripts.json"
        cov = (cm_an.get(name) or {}).get("coverage") or {}
        rows.append({
            "name": name, "slug": slug,
            "market": cfg.get("market"), "label": cfg.get("label"),
            "dynamic": name in dyn,
            "n_calls": cov.get("n_calls"),
            "in_engine": name in cm_an,
            "transcripts_mtime": (
                __import__("datetime").date.fromtimestamp(tpath.stat().st_mtime).isoformat()
                if tpath.exists() else None),
        })
    return rows


def _incremental_rebuild(name: str) -> None:
    """只重算這一位（引擎 --only，其他人沿用快取）→ 建站 → 回歸。refresh/recalc 共用。"""
    import subprocess
    steps = [
        (f"引擎增量重算（只算 {name}）", [sys.executable, "build_calendar_multi.py", "--only", name]),
        ("生成 index.html",            [sys.executable, "generate_site.py"]),
        ("回歸驗證（其他人數字未被動）", [sys.executable, "regression_test.py"]),
    ]
    for i, (desc, cmd) in enumerate(steps, 1):
        print(f"▶ 重建 {i}/{len(steps)}：{desc}…", flush=True)
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            sys.exit(f"✗ 「{desc}」失敗（exit {r.returncode}），中止")


def refresh(name: str) -> None:
    """重抓該分析師逐字稿＋重抽取（增量，已快取影片會跳過），再只重算這一位。
    ★ 只動這個人：引擎走 --only，其他 13 位沿用快取、數字不變（也不會被多花時間重算）。"""
    dyn = _load_registry()
    if name not in dyn:
        sys.exit(f"✗ 「{name}」不是動態註冊的分析師（內建者的資料管線不同，不支援此指令）")
    audit_p = AUDIT_DIR / f"{name}.json"
    if not audit_p.exists():
        sys.exit(f"✗ 找不到 {audit_p}（refresh 需要 audit 卡裡的 channel_id）")
    audit = json.loads(audit_p.read_text(encoding="utf-8"))
    ch_id, typ, slug = audit["channel_id"], audit.get("type"), dyn[name]["slug"]
    import add_analyst
    if typ == "forecast":
        add_analyst.run_forecast_pipeline(name, slug, ch_id, days=1095)
    else:
        add_analyst.run_call_pipeline(name, slug, ch_id, days=1095)
    _incremental_rebuild(name)
    print(f"✅ {name} 已更新（只重算這一位）。注意：BACKTEST_END 凍結於 2026-06-01，"
          "凍結日後的新內容會入紀錄但不改計分。")


def remove(name: str) -> None:
    """軟移除：只從註冊表拿掉（data_cache 資料檔保留，可隨時加回），再全站重建。"""
    dyn = _load_registry()
    if name not in dyn:
        sys.exit(f"✗ 「{name}」不在動態註冊表（內建 13 位寫死於 analysts.py，不能由此移除）")
    dyn.pop(name)
    REGISTRY.write_text(json.dumps(dyn, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"▶ 已自註冊表移除 {name}（資料檔保留於 data_cache/，重跑 add_analyst 可復原）")
    import add_analyst
    rb = add_analyst.rebuild_all()
    if rb.get("_halted_at"):
        sys.exit(1)


# 合併後的單一 repo：程式碼 + 成品站同在此，Pages 從 docs/ 出站
DEPLOY_DIR = Path.home() / "Desktop" / "kol-track-record-src"   # 本機 clone 的 code+site repo
DEPLOY_REPO = "KOL-Track-Record"                                # GitHub repo 名

def deploy() -> None:
    """把最新 index.html 發布到 GitHub Pages（合併 repo 的 docs/index.html）。
    只做 copy → commit → push；repo 與 Pages 已建立好。
    需要：gh 已登入（gh auth login，一次性）。"""
    import subprocess, shutil
    def sh(*cmd, cwd=None, ok_fail=False):
        r = subprocess.run(cmd, cwd=cwd or DEPLOY_DIR, capture_output=True, text=True)
        if r.returncode != 0 and not ok_fail:
            sys.exit(f"✗ {' '.join(cmd)}\n{r.stderr.strip() or r.stdout.strip()}")
        return r
    src = ROOT / "index.html"
    if not src.exists():
        sys.exit("✗ 找不到 index.html，先建站")
    if not shutil.which("gh"):
        sys.exit("✗ 需要 GitHub CLI：brew install gh && gh auth login")
    if sh("gh", "auth", "status", cwd=ROOT, ok_fail=True).returncode != 0:
        sys.exit("✗ GitHub 尚未登入：終端機跑一次 `gh auth login`（選 GitHub.com → HTTPS → browser）")
    if not (DEPLOY_DIR / ".git").exists():
        sys.exit(f"✗ 找不到部署 repo：{DEPLOY_DIR}\n  請先 clone：git clone https://github.com/henrylin1009/{DEPLOY_REPO}.git \"{DEPLOY_DIR}\"")

    docs = DEPLOY_DIR / "docs"
    docs.mkdir(exist_ok=True)
    shutil.copy2(src, docs / "index.html")
    sh("git", "add", "-A")
    from datetime import datetime
    msg = f"publish {datetime.now():%Y-%m-%d %H:%M}"
    if sh("git", "commit", "-m", msg, ok_fail=True).returncode != 0:
        print("（內容沒變，不用重新發布）"); return
    sh("git", "push")
    user = sh("gh", "api", "user", "-q", ".login").stdout.strip()
    print(f"✅ 已發布 → https://{user}.github.io/{DEPLOY_REPO}/（CDN 更新約 1 分鐘）")


import re as _re
# 樣式拆開拼接，避免這行源碼本身命中自己的掃描（同步時會掃 staged diff）
_SECRET_RE = _re.compile("|".join([
    r"sk-[a-zA-Z0-9]{20}",
    "aws_secret" + "_access_key",
    "-----" + "BEGIN",
    r"AKIA[0-9A-Z]{16}",
]), _re.I)

def sync_code() -> None:
    """把本機源碼（.py/.html/.md/requirements）同步進 repo 夾 → 掃祕密 → commit → push。
    只送該公開的原始碼，不碰 .env / 大檔（repo 的 .gitignore 也會擋）。
    解決『deploy 只推 index.html、.py 源碼會漂移』的問題。一鍵讓 GitHub 反映最新程式碼。"""
    import subprocess, shutil, fnmatch
    from datetime import datetime
    if not (DEPLOY_DIR / ".git").exists():
        sys.exit(f"✗ 找不到 repo：{DEPLOY_DIR}")
    def sh(*cmd, ok_fail=False):
        r = subprocess.run(cmd, cwd=DEPLOY_DIR, capture_output=True, text=True)
        if r.returncode != 0 and not ok_fail:
            sys.exit(f"✗ {' '.join(cmd)}\n{r.stderr.strip() or r.stdout.strip()}")
        return r
    # 要同步的源碼型別（相對 ROOT 的頂層檔）；明確排除祕密檔
    patterns = ("*.py", "*.html", "*.md", "requirements.txt", ".env.example")
    skip = {".env", ".env.local"}
    copied = []
    for f in sorted(ROOT.iterdir()):
        if not f.is_file() or f.name in skip:
            continue
        if any(fnmatch.fnmatch(f.name, p) for p in patterns):
            shutil.copy2(f, DEPLOY_DIR / f.name)
            copied.append(f.name)
    print(f"▶ 同步 {len(copied)} 個源碼檔 → repo")
    sh("git", "add", "-A")
    # 提交前掃 staged diff 有沒有祕密
    diff = sh("git", "diff", "--cached").stdout
    if _SECRET_RE.search(diff):
        sys.exit("✗ staged 內容偵測到疑似祕密，已中止（請檢查後手動處理）")
    if sh("git", "commit", "-m", f"sync source {datetime.now():%Y-%m-%d %H:%M}", ok_fail=True).returncode != 0:
        print("（源碼沒變，無需提交）"); return
    sh("git", "push")
    print("✅ 源碼已同步並推上 GitHub")


REBUILD_STEPS = {   # step 名 → (說明, script)；all 依序全跑
    "engine": ("引擎重算 calendar_multi.json", "build_calendar_multi.py"),
    "site":   ("生成 index.html",             "generate_site.py"),
    "verify": ("回歸驗證（既有數字未被動）",     "regression_test.py"),
}

def recalc(name: str) -> None:
    """只重算一位（引擎 --only，其他人沿用快取）→ 建站 → 回歸驗證。
    約 10–15 秒起（vs 全重算 2.5 分鐘）；對內建與動態分析師皆可用。"""
    _incremental_rebuild(name)
    print(f"✅ 完成：{name} 已重算，其他人沿用快取、回歸通過。")


def rebuild(step: str = "all") -> None:
    """step=all 依序跑三步（同 add_analyst 的 rebuild_all）；否則只跑指定那步。
    注意：單跑 engine 後網站仍是舊數字，記得接著跑 site。"""
    import subprocess
    names = list(REBUILD_STEPS) if step == "all" else [step]
    for i, s in enumerate(names, 1):
        desc, script = REBUILD_STEPS[s]
        print(f"▶ {i}/{len(names)}：{desc}…", flush=True)
        r = subprocess.run([sys.executable, script], cwd=ROOT)
        if r.returncode != 0:
            sys.exit(f"✗ 「{desc}」失敗（exit {r.returncode}），中止")
    if step == "engine":
        print("⚠ 引擎已重算，但 index.html 還是舊的 — 要更新網站請再跑 site。")
    print("✅ 完成：" + "、".join(REBUILD_STEPS[s][0] for s in names))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("refresh").add_argument("name")
    sub.add_parser("remove").add_argument("name")
    sub.add_parser("recalc").add_argument("name")
    sub.add_parser("deploy")
    sub.add_parser("sync-code")
    sub.add_parser("rebuild").add_argument(
        "step", nargs="?", default="all", choices=["all", *REBUILD_STEPS])
    args = ap.parse_args()
    os.chdir(ROOT)
    if args.cmd == "list":
        print(json.dumps(roster(), ensure_ascii=False, indent=2))
    elif args.cmd == "refresh":
        refresh(args.name)
    elif args.cmd == "remove":
        remove(args.name)
    elif args.cmd == "recalc":
        recalc(args.name)
    elif args.cmd == "deploy":
        deploy()
    elif args.cmd == "sync-code":
        sync_code()
    elif args.cmd == "rebuild":
        rebuild(args.step)
