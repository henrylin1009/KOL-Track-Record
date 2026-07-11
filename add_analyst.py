"""
add_analyst.py — 統一 SOP 主流程：一行指令加一個分析師

用法：
  python add_analyst.py "@wuchangye" --name 吳昌華
  python add_analyst.py "https://www.youtube.com/@someone"

流程（全自動、不暫停；決策寫進審計卡）：
  1 解析頻道(yt-dlp)  2 判型(classify_analyst)  3 抓逐字稿(抗限流)
  4 字幕可得性檢查    5 路由抽取：預言型→extract_predictions；喊單型→extract_decisions（皆 LLM，端到端）
  6 標的解析(全清冊/成分籃/市場代表)  7 寫審計卡
  8 自動重建：引擎(build_calendar_multi) → 建站(generate_site) → 回歸驗證(regression_test)
    （--no-rebuild 可只做抽取+註冊，事後手動跑三步）

公正三保證：規則統一、決策寫審計卡、設定(sector_basket/tw_name_map)公開可改。
自動重建含回歸驗證：新分析師只是多一列，不應動到既有 13 人 headline；
若被動到，regression_test 非零退出、印在終端，不會靜默改站。

注意：預言型與喊單型皆端到端全自動。喊單型全遷後走 load_decisions（讀
{slug}_decisions.json，標的於引擎端 resolve_target 解析、universe=tw），
不再依賴 build_sentiment_groq 全市場情緒評分（該舊管線已移入 archive/）。
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from datetime import date
from pathlib import Path

AUDIT_DIR = Path("audit"); AUDIT_DIR.mkdir(exist_ok=True)
REGISTRY = Path("data_cache/analysts_registry.json")
MIN_SUB_RATE = 0.5
MIN_VIDEOS = 20
MARKET_KW = re.compile(
    "股|美股|比特|幣|黃金|港股|A股|台股|納斯達|道瓊|標普|英偉達|特斯拉|谷歌|"
    "S&P|NASDAQ|Bitcoin|gold|stock|market|大盤|預測|台積|聯發|解盤|盤勢")


def resolve_channel(url_or_handle: str) -> dict:
    import yt_dlp   # 延遲 import：僅抓頻道需要；重建/驗證路徑不依賴它
    opts = {"quiet": True, "extract_flat": True, "skip_download": True,
            "playlistend": 60, "ignoreerrors": True}
    u = url_or_handle
    if u.startswith("@"):
        u = f"https://www.youtube.com/{u}/videos"
    elif "/videos" not in u and "youtube.com" in u:
        u = u.rstrip("/") + "/videos"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(u, download=False)
    ents = info.get("entries") or []
    titles = [e.get("title", "") for e in ents if e]
    return {
        "channel_id": info.get("channel_id") or info.get("uploader_id"),
        "channel_title": info.get("title", ""),
        "uploader_url": info.get("uploader_url", ""),
        "n_scanned": len(ents),
        "titles": titles,
        "market_titles": [t for t in titles if MARKET_KW.search(t)],
    }


def _slugify(name: str, channel_id: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "", name or "")
    return s.lower() if s else (channel_id or "ch")[-12:]


def register_analyst(name: str, cfg: dict) -> None:
    """寫進 data_cache/analysts_registry.json（analysts.py 載入時合併進 ANALYSTS）。"""
    REGISTRY.parent.mkdir(exist_ok=True)
    reg = json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
    reg[name] = cfg
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"▶ 已註冊 → {REGISTRY}（{name}）")


def run_forecast_pipeline(name: str, slug: str, channel_id: str, days: int) -> dict:
    """預言型端到端：抓逐字稿 → 抽預言 → 建價格宇宙 → 寫註冊表。"""
    from fetch_transcripts import fetch_channel
    from extract_predictions import extract_channel, ASSET_TICKER
    import ensure_prices

    print(f"▶ 1/4 抓逐字稿（slug={slug}）…")
    fetch_channel(channel_id, slug=slug, name=name, days=days)
    print("▶ 2/4 抽取多資產預言…")
    rows = extract_channel(slug)
    assets = {p.get("asset") for v in rows for p in v.get("predictions", [])}
    tickers = {ASSET_TICKER[a] for a in assets if a in ASSET_TICKER} | {"SPY"}
    print(f"▶ 3/4 建價格宇宙（{len(tickers)} 檔：{'、'.join(sorted(tickers))}）…")
    ensure_prices.build_px_cache(tickers, slug)
    cfg = dict(slug=slug, loader_key="forecast", universe=slug,
               market="多資產", label="大盤擇時", is_market_bet=True, start="2020-03-01")
    print("▶ 4/4 寫註冊表…")
    register_analyst(name, cfg)
    n_pred = sum(len(v.get("predictions", [])) for v in rows)
    return {"slug": slug, "n_pred": n_pred, "assets": sorted(assets), "registered": cfg}


def rebuild_all() -> dict:
    """註冊完成後自動接三步：引擎 → 建站 → 回歸驗證（同一把尺，不個別修正）。
    每步用 subprocess 跑（generate_site 為模組頂層執行、引擎有 __main__ 副作用，
    子行程確保乾淨狀態）。回歸驗證失敗 = 既有 13 人數字被動到 → 非零退出碼擋下。
    新分析師只是多一列，不應改動他人 headline；回歸應綠燈通過。"""
    steps = [
        ("引擎重算 calendar_multi.json", [sys.executable, "build_calendar_multi.py"]),
        ("生成 index.html",              [sys.executable, "generate_site.py"]),
        ("回歸驗證（既有數字未被動）",    [sys.executable, "regression_test.py"]),
    ]
    out = {}
    for i, (desc, cmd) in enumerate(steps, 1):
        print(f"\n▶ 重建 {i}/{len(steps)}：{desc}…")
        r = subprocess.run(cmd, capture_output=True, text=True)
        tail = (r.stdout or "").strip().splitlines()[-3:]
        for ln in tail:
            print(f"    {ln}")
        if r.returncode != 0:
            print(f"  ✗ 失敗（returncode={r.returncode}）")
            if r.stderr:
                print("    " + "\n    ".join(r.stderr.strip().splitlines()[-5:]))
            out[desc] = {"ok": False, "returncode": r.returncode}
            out["_halted_at"] = desc
            return out
        out[desc] = {"ok": True}
    print("\n✅ 重建完成：引擎、網站已更新，回歸驗證通過（既有 13 人數字未變）。")
    return out


def run_call_pipeline(name: str, slug: str, channel_id: str, days: int) -> dict:
    """喊單型端到端：抓逐字稿 → 抽買賣決策(extract_decisions,LLM) → 寫註冊表。
    ★ 全遷後喊單型走 load_decisions（非 build_sentiment_groq 情緒管線）：
      標的在引擎端由 resolve_target 解析、universe='tw'（台股價格已在
      full_price_cache.pkl），故此處不建價格宇宙——與預言型的差別僅抽取器與宇宙。"""
    from fetch_transcripts import fetch_channel
    from extract_decisions import extract_rows

    print(f"▶ 1/3 抓逐字稿（slug={slug}）…")
    rows = fetch_channel(channel_id, slug=slug, name=name, days=days)
    print("▶ 2/3 抽取買賣決策（extract_decisions）…")
    dec_rows = extract_rows(rows, slug)
    n_dec = sum(len(r.get("decisions", [])) for r in dec_rows)
    cfg = dict(slug=slug, loader_key="decisions", universe="tw",
               market="台股", label="個股選股", is_market_bet=False,
               start="2024-04-01", call_mode="topbottom")
    print("▶ 3/3 寫註冊表…")
    register_analyst(name, cfg)
    return {"slug": slug, "n_decisions": n_dec, "n_videos": len(dec_rows), "registered": cfg}


def run(url_or_handle: str, name: str | None, rebuild: bool = True):
    print(f"▶ 解析頻道：{url_or_handle}")
    ch = resolve_channel(url_or_handle)
    nm = name or ch["channel_title"]
    print(f"  頻道：{ch['channel_title']} | id={ch['channel_id']} | 掃 {ch['n_scanned']} 部，市場相關 {len(ch['market_titles'])}")

    print("▶ 判型（classify_analyst）…")
    from classify_analyst import classify   # 延遲 import：判型才需要（連 LLM/dotenv）
    cls = classify(ch["market_titles"] or ch["titles"])
    print(f"  型別={cls.get('type')}（{cls.get('confidence')}）：{cls.get('reason','')[:60]}")

    audit = {
        "handle": url_or_handle, "name": nm,
        "channel_id": ch["channel_id"], "channel_title": ch["channel_title"],
        "type": cls.get("type"), "type_confidence": cls.get("confidence"),
        "type_reason": cls.get("reason"),
        "n_videos_scanned": ch["n_scanned"],
        "n_market_related": len(ch["market_titles"]),
        "run_at": str(date.today()),
        "next_steps": [],
    }

    # 字幕可得性（粗檢）：市場相關不足直接擋，不跑管線
    enough = len(ch["market_titles"]) >= MIN_VIDEOS

    if cls.get("type") == "forecast" and enough:
        slug = _slugify(nm, ch["channel_id"])
        audit["slug"] = slug
        audit["resolve_rule"] = "預言型：資產層級對映（asset→SPY/BTC/GLD/EWH/FXI/EWT）"
        try:
            pipe = run_forecast_pipeline(nm, slug, ch["channel_id"], days=1095)
            audit["pipeline"] = pipe
            if rebuild:
                audit["rebuild"] = rebuild_all()
            else:
                audit["next_steps"] = [
                    "engine: python build_calendar_multi.py",
                    "site:   python generate_site.py",
                    "verify: python regression_test.py",
                ]
        except Exception as e:
            audit["pipeline_error"] = f"{type(e).__name__}: {e}"
            audit["next_steps"] = ["管線中斷，見 pipeline_error；修正後重跑 add_analyst"]
    elif cls.get("type") == "forecast":
        audit["next_steps"] = [f"資料不足（市場相關 {len(ch['market_titles'])} < {MIN_VIDEOS}），未跑管線"]
    elif cls.get("type") == "call" and enough:
        slug = _slugify(nm, ch["channel_id"])
        audit["slug"] = slug
        audit["resolve_rule"] = "喊單型：extract_decisions 抽買賣決策→resolve_target 名稱轉代碼（個股直接用、產業用 sector_basket 成分等權籃）；universe=tw"
        try:
            pipe = run_call_pipeline(nm, slug, ch["channel_id"], days=1095)
            audit["pipeline"] = pipe
            if rebuild:
                audit["rebuild"] = rebuild_all()
            else:
                audit["next_steps"] = [
                    "engine: python build_calendar_multi.py",
                    "site:   python generate_site.py",
                    "verify: python regression_test.py",
                ]
        except Exception as e:
            audit["pipeline_error"] = f"{type(e).__name__}: {e}"
            audit["next_steps"] = ["管線中斷，見 pipeline_error；修正後重跑 add_analyst"]
    elif cls.get("type") == "call":
        audit["next_steps"] = [f"資料不足（市場相關 {len(ch['market_titles'])} < {MIN_VIDEOS}），未跑管線"]
    else:
        audit["next_steps"] = ["判型失敗或信心低 → 人工覆核 type 後重跑"]

    # 字幕可得性（粗檢：用市場相關比例當代理；實抓在 fetch 階段）
    if len(ch["market_titles"]) < MIN_VIDEOS:
        audit["included"] = False
        audit["exclude_reason"] = f"市場相關影片僅 {len(ch['market_titles'])} 部 < {MIN_VIDEOS}，資料不足"
    else:
        audit["included"] = True

    path = AUDIT_DIR / f"{nm}.json"
    json.dump(audit, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"▶ 審計卡 → {path}")
    print(f"  included={audit['included']}　待辦：")
    for s in audit["next_steps"]:
        print(f"    - {s}")
    if audit.get("pipeline"):
        pp = audit["pipeline"]
        print(f"\n✅ 預言型已端到端完成：{pp['n_pred']} 條預言、資產 {pp['assets']}、已註冊。")
        rb = audit.get("rebuild")
        if rb and not rb.get("_halted_at"):
            print("   引擎+網站已自動重建、回歸通過。開 index.html 即見新卡片。")
        elif rb:
            print(f"   ⚠ 自動重建在「{rb['_halted_at']}」中斷，見上方錯誤。")
        else:
            print("   接著跑：python build_calendar_multi.py && python generate_site.py")
    else:
        print("\n（喊單型情緒抽取仍沿用既有管線，見待辦。）")
    return audit


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="@handle 或頻道 URL")
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-rebuild", action="store_true",
                    help="只抽取+註冊，不自動接引擎/建站/回歸（預設會自動重建）")
    args = ap.parse_args()
    run(args.target, args.name, rebuild=not args.no_rebuild)
