"""
server.py — FastAPI 後端，提供 AI 問答 API + 靜態網站服務。

啟動：
  source .venv/bin/activate
  python server.py          # 預設 http://localhost:8000
  # 或 uvicorn server:app --reload --port 8000
"""
import asyncio
import collections
import json
import os
import subprocess
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel


# ── 啟動時預載引擎（價格快取 + RAG 索引）──────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時一次性載入重資源，避免首次請求等太久。"""
    print("⏳ 預載引擎…")
    # 價格快取 + 分析師註冊表（ask_query 第一次呼叫會 _boot）
    import ask_query
    ask_query._boot()
    print("  ✅ 價格快取 + 分析師註冊表 已載入")
    # RAG 索引（ask_transcript 第一次 search 會 _load_index）
    try:
        import ask_transcript
        ask_transcript._get_model()
        for slug in ask_transcript.available_slugs():
            ask_transcript._load_index(slug)
        print(f"  ✅ RAG 索引({ask_transcript.available_slugs()}) + embedding 模型 已載入")
    except Exception as e:
        print(f"  ⚠️ RAG 索引載入失敗（AI 問答可能不完整）：{e}")
    print("🚀 Server 就緒")
    yield


app = FastAPI(title="投顧戰績實驗室", lifespan=lifespan)


# ── API Endpoints ──────────────────────────────────────────
class AskRequest(BaseModel):
    question: str
    history: list = []


@app.post("/api/ask")
async def api_ask(req: AskRequest):
    """呼叫合併 agent（DeepSeek tool calling + 逐字稿 RAG），回傳完整答案。"""
    import ask_combined
    try:
        # ask_combined.ask() 是同步的（內含 API 呼叫），用 run_in_executor 避免阻塞
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None, lambda: ask_combined.ask(req.question, history=req.history))
        return {"answer": answer}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/analysts")
async def api_analysts():
    """回傳所有可查的分析師清單（供前端自動完成 / 範例用）。"""
    import ask_query
    return ask_query.list_analysts()


# ── 公開 SQL 遊樂場（訪客打 SQL → Athena，唯讀護欄 + 簡易限流）──
class SqlRequest(BaseModel):
    sql: str

_sql_hits: dict = {}          # ip → [timestamps]（滑動視窗限流）
_SQL_WINDOW = 60.0            # 秒
_SQL_MAX = 20                 # 每 IP 每分鐘上限

def _sql_rate_ok(ip: str) -> bool:
    import time as _t
    now = _t.time()
    q = [t for t in _sql_hits.get(ip, []) if now - t < _SQL_WINDOW]
    if len(q) >= _SQL_MAX:
        _sql_hits[ip] = q
        return False
    q.append(now); _sql_hits[ip] = q
    return True


@app.post("/api/sql")
async def api_sql(req: SqlRequest, request: Request):
    """跑訪客 SQL（Athena，SELECT-only + 自動 LIMIT + 限流）。"""
    import athena_query
    ip = request.client.host if request.client else "?"
    if not _sql_rate_ok(ip):
        return JSONResponse(status_code=429, content={"error": "查詢太頻繁，請稍候再試（每分鐘上限 20 次）"})
    try:
        loop = asyncio.get_event_loop()
        out = await loop.run_in_executor(None, lambda: athena_query.run_sql(req.sql))
        return out
    except athena_query.SqlError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"查詢失敗：{e}"})


# ── 管理面板（僅限本機：server 綁 0.0.0.0，admin 端點須擋非 localhost）──
ROOT = os.path.dirname(__file__)

def _admin_only(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="admin 僅限本機存取")


# 單一背景 job（同時只跑一個，避免併發重建互相覆寫 calendar_multi.json）
_job = {"running": False, "name": None, "rc": None,
        "log": collections.deque(maxlen=800)}
_job_lock = threading.Lock()

def _start_job(name: str, cmd: list[str]) -> bool:
    with _job_lock:
        if _job["running"]:
            return False
        _job.update(running=True, name=name, rc=None)
        _job["log"].clear()
    def worker():
        _job["log"].append(f"$ {' '.join(cmd)}")
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in p.stdout:
                _job["log"].append(line.rstrip())
            p.wait()
            _job["rc"] = p.returncode
        except Exception as e:
            _job["log"].append(f"✗ {type(e).__name__}: {e}")
            _job["rc"] = -1
        _job["running"] = False
    threading.Thread(target=worker, daemon=True).start()
    return True


class AdminAdd(BaseModel):
    url: str
    name: str | None = None

class AdminName(BaseModel):
    name: str


@app.get("/admin")
async def admin_page(request: Request):
    _admin_only(request)
    return FileResponse(os.path.join(ROOT, "admin.html"), media_type="text/html")


@app.get("/api/admin/roster")
async def admin_roster(request: Request):
    _admin_only(request)
    import manage
    import config
    return {"backtest_end": config.BACKTEST_END, "roster": manage.roster()}


@app.get("/api/admin/job")
async def admin_job(request: Request):
    _admin_only(request)
    return {"running": _job["running"], "name": _job["name"],
            "rc": _job["rc"], "log": list(_job["log"])}


@app.post("/api/admin/add")
async def admin_add(req: AdminAdd, request: Request):
    _admin_only(request)
    cmd = [sys.executable, "add_analyst.py", req.url]
    if req.name:
        cmd += ["--name", req.name]
    ok = _start_job(f"新增：{req.name or req.url}", cmd)
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


@app.post("/api/admin/recalc")
async def admin_recalc(req: AdminName, request: Request):
    _admin_only(request)
    ok = _start_job(f"重算：{req.name}", [sys.executable, "manage.py", "recalc", req.name])
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


@app.post("/api/admin/deploy")
async def admin_deploy(request: Request):
    _admin_only(request)
    ok = _start_job("發布上線（GitHub Pages）", [sys.executable, "manage.py", "deploy"])
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


@app.post("/api/admin/refresh")
async def admin_refresh(req: AdminName, request: Request):
    _admin_only(request)
    ok = _start_job(f"更新：{req.name}", [sys.executable, "manage.py", "refresh", req.name])
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


@app.post("/api/admin/remove")
async def admin_remove(req: AdminName, request: Request):
    _admin_only(request)
    ok = _start_job(f"移除：{req.name}", [sys.executable, "manage.py", "remove", req.name])
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


class AdminRebuild(BaseModel):
    step: str = "all"   # all | engine | site | verify

@app.post("/api/admin/rebuild")
async def admin_rebuild(req: AdminRebuild, request: Request):
    _admin_only(request)
    if req.step not in ("all", "engine", "site", "verify"):
        raise HTTPException(status_code=400, detail=f"未知 step：{req.step}")
    label = {"all": "全站重建", "engine": "引擎重算", "site": "重新建站", "verify": "回歸驗證"}[req.step]
    ok = _start_job(label, [sys.executable, "manage.py", "rebuild", req.step])
    return {"started": ok} if ok else JSONResponse(status_code=409, content={"error": "已有任務進行中"})


# ── 靜態網站 ────────────────────────────────────────────────
@app.get("/sql")
async def sql_page():
    """SQL 遊樂場頁（訪客用 Athena 查回測資料）。"""
    return FileResponse(os.path.join(ROOT, "sql.html"), media_type="text/html")


@app.get("/")
async def index():
    """回傳生成好的 index.html。"""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    return FileResponse(html_path, media_type="text/html")


# ── 直接執行 ────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)
