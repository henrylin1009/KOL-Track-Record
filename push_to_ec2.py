#!/usr/bin/env python3
"""
push_to_ec2.py — 一鍵把本機更新推到 EC2 並重啟服務。

用法：
  python push_to_ec2.py            # 快速推：程式 + 網頁 + 小型 JSON（不含大索引）
  python push_to_ec2.py --full     # 全推：連 RAG 索引 + 價格快取（換資料/加分析師時用）
  EC2_HOST=1.2.3.4 python push_to_ec2.py   # 機器重開 IP 變了，用 EC2_HOST 覆蓋

前提：SSH 金鑰在 ~/.ssh/kol-deploy.pem（部署時建立的那把）。
安全：管理操作留在本機，這支只是把「本機算好的成果」單向推上公開站。
"""
import os
import subprocess
import sys

HOST = os.environ.get("EC2_HOST", "13.238.128.215")   # 機器重開 IP 會變 → 用 EC2_HOST 覆蓋
USER = "ec2-user"
PEM = os.path.expanduser("~/.ssh/kol-deploy.pem")
REMOTE = f"{USER}@{HOST}:~/app/"
SSH = f"ssh -o StrictHostKeyChecking=no -i {PEM}"

# 一律排除：本機環境 / 快取 / 備份 / 圖表 / 大 DB / Athena 已有的檔
BASE_EXCLUDES = [
    ".venv", ".git", "__pycache__", "*.pyc", "*.pkl.bak", "price_cache.pkl",
    "*.db", "*.png", "*.csv", "*.log", "archive", "data_cache/calls_flat.*",
    "backtest_result*",
]
# 快速模式額外排除：大索引 + 價格快取（很少變、換資料才需要 --full）
FAST_EXCLUDES = ["*.pkl", "data_cache/*_rag_index.pkl", "data_cache/*_transcripts.json"]


def run(cmd, **kw):
    print(f"$ {cmd}")
    return subprocess.run(cmd, shell=True, **kw)


def main():
    full = "--full" in sys.argv
    if not os.path.exists(PEM):
        sys.exit(f"✗ 找不到 SSH 金鑰 {PEM}")

    excludes = list(BASE_EXCLUDES) + ([] if full else FAST_EXCLUDES)
    ex_flags = " ".join(f"--exclude='{e}'" for e in excludes)
    mode = "全推（含索引/快取）" if full else "快速推（程式 + 網頁 + JSON）"
    print(f"▶ {mode} → {HOST}\n")

    # 1) rsync
    rc = run(f"rsync -az {ex_flags} -e \"{SSH}\" ./ {REMOTE}").returncode
    if rc != 0:
        sys.exit(f"✗ rsync 失敗（rc={rc}）——機器 IP 變了嗎？可 EC2_HOST=新IP 再跑")

    # 2) 重啟服務
    run(f"{SSH} {USER}@{HOST} 'sudo systemctl restart kol'")

    # 3) 健康檢查（等預載）
    print("等服務就緒…")
    check = (f"{SSH} {USER}@{HOST} "
             f"'for i in $(seq 1 24); do "
             f"[ \"$(curl -s -o /dev/null -w %{{http_code}} http://localhost:8000/sql)\" = 200 ] "
             f"&& {{ echo READY; exit 0; }}; sleep 5; done; echo TIMEOUT'")
    out = subprocess.run(check, shell=True, capture_output=True, text=True).stdout.strip()
    if "READY" in out:
        print(f"\n✅ 完成！live 站已更新：http://{HOST}:8000")
    else:
        print(f"\n⚠ 服務重啟後沒在時限內就緒，去看 log：")
        print(f"   {SSH} {USER}@{HOST} 'sudo journalctl -u kol --no-pager | tail -30'")


if __name__ == "__main__":
    main()
