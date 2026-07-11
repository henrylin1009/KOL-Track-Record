"""
fetch_transcripts.py — 通用逐字稿抓取（泛化自 fetch_wu_transcripts.py）

吃任一頻道 channel_id（或 @handle）→ 抓市場相關影片字幕 → 存
  data_cache/{slug}_transcripts.json
抗限流、增量續抓（已抓過的跳過）、市場關鍵字過濾。可被 add_analyst.py 程式呼叫。

用法（CLI）：
  python fetch_transcripts.py --channel-id UCxxxx --name 吳昌華 --days 1095
  python fetch_transcripts.py --handle @wuchangye --name 吳昌華
程式呼叫：
  from fetch_transcripts import fetch_channel
  rows = fetch_channel("UCxxxx", slug="wu", days=1095)
"""
from __future__ import annotations
import argparse, json, re, time
from datetime import date, timedelta
from pathlib import Path
import yt_dlp
from youtube_fetcher import fetch_subtitle_text

HARD_LIMIT = 1000

# 只留含市場關鍵字的影片（與 add_analyst.py 同一把尺）
MARKET_KW = re.compile(
    "股|美股|比特|幣|黃金|港股|A股|台股|納斯達|道瓊|標普|英偉達|特斯拉|谷歌|"
    "S&P|NASDAQ|Bitcoin|gold|stock|market|SpaceX|AI牛|美元|原油|大盤|預測|台積|聯發|解盤|盤勢")


def _slugify(name: str, channel_id: str) -> str:
    """產生英數安全的快取檔名片段。優先用 name 的英數，否則用 channel_id 尾段。"""
    s = re.sub(r"[^0-9A-Za-z]+", "", name or "")
    return s.lower() if s else (channel_id or "ch")[-12:]


def resolve_channel_id(handle_or_url: str) -> str:
    """@handle 或 URL → channel_id（UCxxxx）。"""
    u = handle_or_url
    if u.startswith("@"):
        u = f"https://www.youtube.com/{u}/videos"
    elif "youtube.com" in u and "/videos" not in u:
        u = u.rstrip("/") + "/videos"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "ignoreerrors": True, "playlistend": 1}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(u, download=False)
    return (info or {}).get("channel_id") or (info or {}).get("uploader_id") or handle_or_url


def list_video_ids(channel_id: str, name: str, skip_kw: list[str] | None = None) -> list[dict]:
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "ignoreerrors": True, "playlistend": HARD_LIMIT}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = (info.get("entries") or []) if info else []
    skip_kw = skip_kw or []
    videos = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        title = e.get("title", "") or ""
        if any(k in title for k in skip_kw):
            continue
        if not MARKET_KW.search(title):
            continue
        videos.append({"video_id": e["id"], "title": title})
    print(f"[{name}] 掃描 {len(entries)} 部，市場相關 {len(videos)} 部")
    return videos


def get_upload_date(video_id: str) -> str | None:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "ignoreerrors": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False)
        raw = (info or {}).get("upload_date", "")
        if raw and len(raw) == 8:
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        return raw[:10] if raw else None
    except Exception:
        return None


def fetch_channel(channel_id: str, slug: str | None = None, name: str = "",
                  days: int = 1095, force_refresh: bool = False,
                  skip_kw: list[str] | None = None) -> list[dict]:
    """抓一個頻道的市場相關逐字稿 → data_cache/{slug}_transcripts.json。回傳 rows。"""
    slug = slug or _slugify(name, channel_id)
    cache_file = Path(f"data_cache/{slug}_transcripts.json")
    cache_file.parent.mkdir(exist_ok=True)

    existing: dict[str, dict] = {}
    if cache_file.exists() and not force_refresh:
        existing = {r["video_id"]: r for r in json.loads(cache_file.read_text())}
        print(f"[快取] {cache_file.name} 已有 {len(existing)} 筆")

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    videos = list_video_ids(channel_id, name or slug, skip_kw)
    results = list(existing.values())
    new_count = 0
    for i, v in enumerate(videos):
        vid = v["video_id"]
        if vid in existing:
            continue
        upload_date = get_upload_date(vid)
        if not upload_date or upload_date < cutoff:
            continue
        try:
            text = fetch_subtitle_text(vid)
        except Exception as e:
            print(f"  [{i+1}/{len(videos)}] {upload_date} ⏭️ 跳過({type(e).__name__}) {v['title'][:40]}", flush=True)
            time.sleep(8)
            continue
        entry = {"video_id": vid, "title": v["title"], "upload_date": upload_date,
                 "transcript": text, "has_subtitle": text is not None}
        results.append(entry)
        existing[vid] = entry
        new_count += 1
        status = f"✅ {len(text)}字" if text else "❌"
        print(f"  [{i+1}/{len(videos)}] {upload_date} {status} {v['title'][:46]}", flush=True)
        cache_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        time.sleep(3)
    cache_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    n_sub = sum(1 for r in results if r.get("has_subtitle"))
    sub_rate = round(n_sub / len(results), 3) if results else 0.0
    print(f"\n完成：新增 {new_count}，共 {len(results)} 筆"
          f"（有字幕 {n_sub}，字幕率 {sub_rate:.0%}）→ {cache_file}")
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--channel-id", help="UCxxxx 頻道 id")
    g.add_argument("--handle", help="@handle 或頻道 URL")
    p.add_argument("--name", default="", help="中文名（用於 log 與 slug）")
    p.add_argument("--slug", default=None, help="快取檔名片段（預設由 name/channel 推導）")
    p.add_argument("--days", type=int, default=1095)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    cid = args.channel_id or resolve_channel_id(args.handle)
    fetch_channel(cid, slug=args.slug, name=args.name,
                  days=args.days, force_refresh=args.refresh)
