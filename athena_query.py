"""
athena_query.py — 公開 SQL 遊樂場後端：把訪客輸入的 SQL 安全地跑到 Athena。

護欄（唯讀、防呆、防洗）：
  1. 只允許單一 SELECT / WITH 查詢（擋 DDL/DML、擋多語句分號注入）
  2. 沒寫 LIMIT 自動補上（防撈爆 / 防長輸出）
  3. 只能查白名單資料表（calls_flat）
  4. 查詢逾時保護
  5. 簡易 per-IP rate limit（在 server 端呼叫）

設定用環境變數（有預設）：
  ATHENA_DB=default  ATHENA_OUTPUT=s3://kol-track-record/athena-results/
  AWS_REGION=ap-southeast-2
"""
import os
import re
import time

import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
DATABASE = os.environ.get("ATHENA_DB", "default")
OUTPUT = os.environ.get("ATHENA_OUTPUT", "s3://kol-track-record/athena-results/")
ALLOWED_TABLES = {"calls_flat"}       # 只准查這些表
MAX_LIMIT = 500                        # 強制上限，防大輸出
QUERY_TIMEOUT_S = 25                   # 單查逾時
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|merge|grant|revoke|"
    r"msck|load|unload|call|describe|show|set|use|with\s+recursive)\b", re.I)

_client = None
def _athena():
    global _client
    if _client is None:
        _client = boto3.client("athena", region_name=REGION)
    return _client


class SqlError(Exception):
    """使用者 SQL 有問題（回 400 給前端顯示）。"""


def _validate(sql: str) -> str:
    """回傳清理後的安全 SQL；不合規則 raise SqlError。"""
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise SqlError("請輸入 SQL")
    # 只允許單一語句（擋分號注入多語句）
    if ";" in s:
        raise SqlError("一次只能跑一句 SQL（不要用分號串多句）")
    low = s.lower()
    # 必須以 select 或 with 開頭
    if not (low.startswith("select") or low.startswith("with")):
        raise SqlError("只允許 SELECT 查詢（唯讀）")
    # 擋任何寫入/DDL 關鍵字
    if FORBIDDEN.search(s):
        raise SqlError("偵測到不允許的關鍵字：只能做唯讀 SELECT 查詢")
    # 只准查白名單表：粗略檢查出現的識別字裡有沒有非白名單的可疑表名
    # （from/join 後面接的 token）
    refs = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w]*)", low)
    for t in refs:
        if t not in ALLOWED_TABLES:
            raise SqlError(f"只能查這些表：{', '.join(sorted(ALLOWED_TABLES))}（偵測到 {t}）")
    # 沒有 LIMIT 就自動補（有的話夾到 MAX_LIMIT）
    m = re.search(r"\blimit\s+(\d+)\s*$", low)
    if m:
        n = min(int(m.group(1)), MAX_LIMIT)
        s = re.sub(r"\blimit\s+\d+\s*$", f"LIMIT {n}", s, flags=re.I)
    else:
        s = f"{s}\nLIMIT {MAX_LIMIT}"
    return s


def run_sql(sql: str) -> dict:
    """跑一條使用者 SQL，回 {columns, rows, scanned_bytes, ms} 或 raise SqlError。"""
    safe = _validate(sql)
    ath = _athena()
    try:
        qid = ath.start_query_execution(
            QueryString=safe,
            QueryExecutionContext={"Database": DATABASE},
            ResultConfiguration={"OutputLocation": OUTPUT},
        )["QueryExecutionId"]
    except Exception as e:
        raise SqlError(f"查詢啟動失敗：{e}")

    t0 = time.time()
    while True:
        ex = ath.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = ex["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        if time.time() - t0 > QUERY_TIMEOUT_S:
            try:
                ath.stop_query_execution(QueryExecutionId=qid)
            except Exception:
                pass
            raise SqlError("查詢逾時（>25 秒）")
        time.sleep(0.4)

    if state != "SUCCEEDED":
        reason = ex["Status"].get("StateChangeReason", "查詢失敗")
        raise SqlError(reason)

    scanned = ex.get("Statistics", {}).get("DataScannedInBytes", 0)
    res = ath.get_query_results(QueryExecutionId=qid, MaxResults=MAX_LIMIT + 1)
    rows = res["ResultSet"]["Rows"]
    if not rows:
        return {"columns": [], "rows": [], "scanned_bytes": scanned, "ms": int((time.time()-t0)*1000)}
    columns = [c.get("VarCharValue", "") for c in rows[0]["Data"]]
    data = [[c.get("VarCharValue") for c in r["Data"]] for r in rows[1:]]
    return {"columns": columns, "rows": data, "scanned_bytes": int(scanned),
            "ms": int((time.time() - t0) * 1000)}


if __name__ == "__main__":
    import json, sys
    q = " ".join(sys.argv[1:]) or "SELECT analyst, COUNT(*) n FROM calls_flat GROUP BY analyst ORDER BY n DESC"
    print(json.dumps(run_sql(q), ensure_ascii=False, indent=2))
