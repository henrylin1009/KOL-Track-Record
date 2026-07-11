"""YouTube 字幕抓取模組（yt-dlp 為主引擎，youtube-transcript-api 備援）。

設計（對應 PLAN.md 第 1b 節）：
- 主引擎 yt-dlp：原生處理語言標籤錯亂、有 ASR 時抓得更穩、活躍維護。
  取 info 的 subtitles / automatic_captions，挑中文系最佳軌，下載 json3/vtt 解析純文字。
- 備援 youtube-transcript-api：yt-dlp 拿不到時再試一次（兩者覆蓋面略有差異）。
- 語言優先：zh-Hant > zh-TW > zh > zh-Hans > zh-HK > 其餘 zh* > ASR 任一中文。
- 任一影片無字幕 → 回 None，靜默跳過，不中止整體流程。

誠實預期：yt-dlp 變不出「真的沒字幕」的影片；命中率提升主要來自清單回溯加深 +
同一天「字幕版」分身，引擎升級是為了「穩定性」。
"""

from __future__ import annotations

import json
import re
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from yt_dlp import YoutubeDL

import config

# 語言優先序：精確繁中 → 一般中文 → 簡中 → 港中
# ASR 自動字幕的 key 格式為 "zh-Hant-zh"、"zh-Hans-zh"（帶 -zh 後綴），也要涵蓋
PREFERRED_LANGS = ["zh-Hant-zh", "zh-Hans-zh", "zh-Hant", "zh-TW", "zh", "zh-Hans", "zh-HK", "zh-CN"]
MAX_RETRIES = 3
_DATE_RE = re.compile(r"(202[0-9])[./\-](\d{1,2})[./\-](\d{1,2})")

# 共用一個 requests session（字幕檔下載）
_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0"})

# 429 退避設定（秒）：YouTube timedtext 端點會軟限流
_THROTTLE_BACKOFF = [12, 30, 60]


class ThrottleError(Exception):
    """YouTube 軟限流（429/403）——暫時性，呼叫端不應把該影片視為「無字幕」。"""


# --------------------------------------------------------------------------
# 字幕軌挑選與解析
# --------------------------------------------------------------------------
def _pick_lang(tracks: dict) -> Optional[str]:
    """從 {lang: [fmt,...]} 依優先序挑一個語言代碼。"""
    if not tracks:
        return None
    keys = list(tracks.keys())
    # 1) 精確優先序
    for pref in PREFERRED_LANGS:
        for k in keys:
            if k.lower() == pref.lower():
                return k
    # 2) 任一 zh 開頭
    for k in keys:
        if k.lower().startswith("zh"):
            return k
    return None


def _pick_format_url(fmts: list[dict]) -> tuple[Optional[str], str]:
    """從字幕格式清單挑最佳：優先 json3，其次 vtt/srv*，回傳 (url, ext)。"""
    if not fmts:
        return None, ""
    by_ext = {f.get("ext"): f for f in fmts if f.get("url")}
    for ext in ("json3", "srv3", "vtt", "srv1", "ttml"):
        if ext in by_ext:
            return by_ext[ext]["url"], ext
    # 退而求其次取第一個有 url 的
    for f in fmts:
        if f.get("url"):
            return f["url"], f.get("ext", "")
    return None, ""


def _parse_json3(data: dict) -> str:
    out = []
    for ev in data.get("events", []) or []:
        for seg in ev.get("segs", []) or []:
            t = seg.get("utf8", "")
            if t and t != "\n":
                out.append(t)
    return " ".join(out)


def _parse_vtt(raw: str) -> str:
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or "-->" in ln:
            continue
        if ln.isdigit():
            continue
        if ln.startswith(("Kind:", "Language:", "NOTE")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)  # 去掉行內標籤
        if ln:
            lines.append(ln)
    # 去重連續重複行（auto sub 常見滾動重複）
    dedup = []
    for ln in lines:
        if not dedup or dedup[-1] != ln:
            dedup.append(ln)
    return " ".join(dedup)


def _parse_xml(raw: str) -> str:
    txts = re.findall(r"<text[^>]*>(.*?)</text>", raw, flags=re.DOTALL)
    if not txts:
        txts = re.findall(r"<p[^>]*>(.*?)</p>", raw, flags=re.DOTALL)
    import html
    out = []
    for t in txts:
        t = re.sub(r"<[^>]+>", "", t)
        t = html.unescape(t).strip()
        if t:
            out.append(t)
    return " ".join(out)


def _download_and_parse(url: str, ext: str) -> Optional[str]:
    r = None
    for attempt in range(len(_THROTTLE_BACKOFF) + 1):
        try:
            r = _session.get(url, timeout=20)
            if r.status_code in (429, 403):
                if attempt < len(_THROTTLE_BACKOFF):
                    wait = _THROTTLE_BACKOFF[attempt]
                    warnings.warn(f"字幕端點限流 {r.status_code}，{wait}s 後重試（{attempt+1}）")
                    time.sleep(wait)
                    continue
                raise ThrottleError(f"持續限流 {r.status_code}（{ext}）")
            r.raise_for_status()
            break
        except ThrottleError:
            raise
        except Exception as e:
            warnings.warn(f"字幕檔下載失敗 ({ext}): {e}")
            return None
    if r is None:
        return None
    try:
        if ext == "json3" or ext == "srv3":
            return _parse_json3(r.json())
        if ext == "vtt":
            return _parse_vtt(r.text)
        # srv1 / ttml / 其餘 XML
        return _parse_xml(r.text)
    except Exception as e:
        warnings.warn(f"字幕解析失敗 ({ext}): {e}")
        return None


def _fetch_via_ytdlp(video_id: str) -> Optional[str]:
    """主引擎：用 yt-dlp 抓字幕（先人工字幕，後 ASR 自動字幕）。"""
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "writesubtitles": True, "writeautomaticsub": True,
        "socket_timeout": 20, "ignoreerrors": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False)
    except Exception as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            raise ThrottleError(f"yt-dlp 解析限流 {video_id}")
        warnings.warn(f"yt-dlp 解析失敗 {video_id}: {e}")
        return None
    if not info:
        return None

    # 先試人工字幕，再試自動字幕
    for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        lang = _pick_lang(tracks)
        if not lang:
            continue
        url, ext = _pick_format_url(tracks[lang])
        if not url:
            continue
        text = _download_and_parse(url, ext)
        if text and len(text) > 50:
            return text
    return None


def _fetch_via_transcript_api(video_id: str) -> Optional[str]:
    """備援引擎：youtube-transcript-api（介面不穩，包在 try 內）。"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return None
    try:
        api = YouTubeTranscriptApi()
        tl = api.list(video_id)
        transcript = None
        for lang in PREFERRED_LANGS:
            try:
                transcript = tl.find_transcript([lang]); break
            except Exception:
                pass
        if transcript is None:
            try:
                transcript = tl.find_generated_transcript(PREFERRED_LANGS)
            except Exception:
                transcript = next(iter(tl))
        parts = transcript.fetch()
        return " ".join(
            (p.text if hasattr(p, "text") else p.get("text", "")) for p in parts
            if (p.text if hasattr(p, "text") else p.get("text"))
        )
    except Exception:
        return None


def fetch_subtitle_text(video_id: str) -> Optional[str]:
    """抓單一影片字幕純文字。yt-dlp 為主，transcript-api 為備援；無字幕回 None。"""
    text = _fetch_via_ytdlp(video_id)
    if text:
        return text
    return _fetch_via_transcript_api(video_id)


# 向後相容別名（舊程式用 _fetch_transcript）
def _fetch_transcript(video_id: str) -> Optional[str]:
    return fetch_subtitle_text(video_id)


# --------------------------------------------------------------------------
# 頻道影片清單（歷史回溯加深；以日期停止條件取代固定 playlistend）
# --------------------------------------------------------------------------
def list_channel_videos(
    channel_id: str,
    channel_name: str,
    start_date: str = config.BACKTEST_START,
    end_date: str = config.BACKTEST_END,
    hard_limit: int = 2500,
) -> list[dict]:
    """列出頻道在 [start_date, end_date] 內的影片。

    用 extract_flat 快速取 id+title，從標題 regex 解析日期。
    日更頻道兩年約 500~700 部，hard_limit 給足緩衝；早於 start_date 仍續掃
    （標題日期不保證單調），但達 hard_limit 即停。
    回傳 [{video_id, title, upload_date, channel_id, channel}, ...]
    """
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "extract_flat": True, "ignoreerrors": True,
        "playlistend": hard_limit, "socket_timeout": 30,
        "no_color": True, "noprogress": True, "consoletitle": False,
    }
    videos: list[dict] = []
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = (info.get("entries") or []) if info else []
        for e in entries:
            if not e or not e.get("id"):
                continue
            title = e.get("title", "") or ""
            m = _DATE_RE.search(title)
            if not m:
                continue
            dt_str = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            if dt_str < start_date or dt_str > end_date:
                continue
            videos.append({
                "video_id": e["id"], "title": title, "upload_date": dt_str,
                "channel_id": channel_id, "channel": channel_name,
            })
        print(f"    [{channel_name}] 掃描 {len(entries)} 部，期間內有日期 {len(videos)} 部")
    except Exception as e:
        warnings.warn(f"[{channel_name}] 影片清單掃描失敗: {e}")
    return videos


# --------------------------------------------------------------------------
# 即時管線用：抓頻道最近 N 天影片字幕（週訊號用）
# --------------------------------------------------------------------------
def fetch_channel_transcripts(
    channel_id: str,
    channel_name: str,
    lookback_days: int = config.SUBTITLE_LOOKBACK_DAYS,
    manual_video_ids: Optional[list[str]] = None,
) -> list[dict]:
    """抓目標頻道最近 N 天的影片字幕（即時週訊號）。"""
    if manual_video_ids:
        vids = [{"video_id": v, "title": "手動提供", "upload_date": "",
                 "channel_id": channel_id, "channel": channel_name}
                for v in manual_video_ids]
    else:
        today = date.today()
        start = (today - timedelta(days=lookback_days)).isoformat()
        vids = list_channel_videos(channel_id, channel_name,
                                   start_date=start, end_date=today.isoformat(),
                                   hard_limit=60)
    results = []
    for v in vids:
        text = fetch_subtitle_text(v["video_id"])
        if text:
            results.append({
                "channel": channel_name, "video_id": v["video_id"],
                "published_at": v.get("upload_date", ""), "title": v["title"],
                "transcript": text,
            })
    return results


def fetch_all_channels(
    channels: list[dict] = config.TARGET_CHANNELS,
    manual_map: Optional[dict[str, list[str]]] = None,
) -> list[dict]:
    """批次抓所有目標頻道（即時管線）。"""
    all_results = []
    for ch in channels:
        cid, name = ch["channel_id"], ch["name"]
        manual = (manual_map or {}).get(cid)
        items = fetch_channel_transcripts(cid, name, manual_video_ids=manual)
        print(f"  [{name}] 撈到 {len(items)} 部影片字幕。")
        all_results.extend(items)
    return all_results
