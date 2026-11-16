"""透過 yt-dlp 取得 YouTube 字幕（人工字幕優先，其次自動字幕）。"""
import json
import re

import yt_dlp

VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})"
)


def parse_video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    m = VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def parse_json3(data: dict) -> list[dict]:
    """把 YouTube json3 字幕轉成 [{start, end, text}]，並去除空白與連續重複。"""
    segments: list[dict] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs or "tStartMs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        start = ev["tStartMs"] / 1000
        end = start + ev.get("dDurationMs", 0) / 1000
        if segments and segments[-1]["text"] == text:
            segments[-1]["end"] = max(segments[-1]["end"], end)
            continue
        segments.append({"start": start, "end": end, "text": text})
    # 避免相鄰字幕時間重疊（自動字幕常見）
    for cur, nxt in zip(segments, segments[1:]):
        if cur["end"] > nxt["start"]:
            cur["end"] = nxt["start"]
    return [s for s in segments if s["end"] > s["start"]]


def _pick_track(info: dict) -> tuple[str, str, list[dict]] | None:
    """回傳 (來源, 語言碼, 格式清單)；來源為 manual 或 auto。"""
    lang = info.get("language") or ""
    base = lang.split("-")[0]  # en-US -> en
    manual = info.get("subtitles") or {}
    manual = {k: v for k, v in manual.items() if k != "live_chat"}
    # 人工字幕也必須是影片本身的語言：常有別人上傳的他語翻譯軌（例如英文影片只有俄文軌），
    # 不能隨便取第一軌，否則會變成「英文 → 俄文 → 中文」。語言不符就改走自動字幕的原始軌。
    key = next((k for k in (lang, base) if k and k in manual), None)
    if key is None and base:
        key = next((k for k in manual if k.split("-")[0] == base), None)  # en-GB 等同語系
    if key:
        return "manual", key, manual[key]
    if not lang and len(manual) == 1:  # 影片語言不明、只有一軌時，除了它也沒有更好的選擇
        key = next(iter(manual))
        return "manual", key, manual[key]
    auto = info.get("automatic_captions") or {}
    # 自動字幕清單會列出很多語言（含 -orig 結尾的軌），不能直接取第一個，
    # 必須以影片本身的語言為準；語言不明且有多個候選時寧可回傳 None 改走 Whisper。
    for k in (f"{lang}-orig", f"{base}-orig", lang, base):
        if k and k != "-orig" and k in auto:
            return "auto", k.removesuffix("-orig"), auto[k]
    orig = [k for k in auto if k.endswith("-orig")]
    if len(orig) == 1:
        return "auto", orig[0].removesuffix("-orig"), auto[orig[0]]
    return None


def fetch_subtitles(video_id: str) -> dict:
    """回傳 {title, lang, source, segments}；無字幕時 segments 為空、source 為 None。"""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
        result = {
            "title": info.get("title", video_id),
            "lang": info.get("language") or "",
            "source": None,
            "segments": [],
            "duration": info.get("duration") or 0,
        }
        picked = _pick_track(info)
        if not picked:
            return result
        source, lang, formats = picked
        fmt = next((f for f in formats if f.get("ext") == "json3"), None)
        if not fmt:
            return result
        raw = ydl.urlopen(fmt["url"]).read()
        segments = parse_json3(json.loads(raw))
        if segments:
            result.update(source=source, lang=lang, segments=segments)
        return result
