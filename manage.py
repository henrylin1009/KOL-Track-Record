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


DEPLOY_DIR = ROOT / "deploy_site"          # 獨立小 git repo：只放 index.html
DEPLOY_REPO = "kol-track-record"           # GitHub repo 名（第一次 deploy 自動建立）

def deploy() -> None:
    """把最新 index.html 發布到 GitHub Pages。
    第一次執行：自動建 repo（gh repo create，public）+ 開 Pages；之後只是 commit+push。
    需要：brew install gh && gh auth login（一次性）。"""
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

    first = not (DEPLOY_DIR / ".git").exists()
    if first:
        print("▶ 第一次發布：建立 deploy_site/ 小 repo…", flush=True)
        DEPLOY_DIR.mkdir(exist_ok=True)
        (DEPLOY_DIR / ".nojekyll").write_text("")   # 關掉 GitHub Pages 的 Jekyll 處理
        sh("git", "init", "-b", "main")
        if subprocess.run(["git", "config", "user.name"], capture_output=True).returncode != 0 \
           or not subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip():
            sh("git", "config", "user.name", "Henry Lin")
    shutil.copy2(src, DEPLOY_DIR / "index.html")
    sh("git", "add", "-A")
    from datetime import datetime
    msg = f"publish {datetime.now():%Y-%m-%d %H:%M}"
    if sh("git", "commit", "-m", msg, ok_fail=True).returncode != 0:
        print("（內容沒變，不用重新發布）"); return
    if first:
        print(f"▶ 建立 GitHub repo：{DEPLOY_REPO}（public）…", flush=True)
        sh("gh", "repo", "create", DEPLOY_REPO, "--public",
           "--source", str(DEPLOY_DIR), "--remote", "origin", "--push")
        print("▶ 開啟 GitHub Pages…", flush=True)
        user = sh("gh", "api", "user", "-q", ".login").stdout.strip()
        sh("gh", "api", f"repos/{user}/{DEPLOY_REPO}/pages", "-X", "POST",
           "-f", "source[branch]=main", "-f", "source[path]=/", ok_fail=True)
        print(f"✅ 上線！約 1–2 分鐘後可看：https://{user}.github.io/{DEPLOY_REPO}/")
    else:
        sh("git", "push")
        user = sh("gh", "api", "user", "-q", ".login").stdout.strip()
        print(f"✅ 已發布 → https://{user}.github.io/{DEPLOY_REPO}/（CDN 更新約 1 分鐘）")


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
    elif args.cmd == "rebuild":
        rebuild(args.step)
