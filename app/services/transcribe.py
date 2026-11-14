"""無字幕時：下載音檔，再用本機 faster-whisper 轉成文字。"""
from pathlib import Path
from typing import Callable

import yt_dlp

from app import config


def download_audio(video_id: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = next(out_dir.glob("audio.*"), None)
    if existing:
        return existing
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "audio.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    path = next(out_dir.glob("audio.*"), None)
    if not path:
        raise RuntimeError("音檔下載失敗")
    return path


def transcribe(
    audio: Path, on_progress: Callable[[float], None] | None = None
) -> tuple[str, list[dict]]:
    """回傳 (偵測到的語言, segments)。"""
    from faster_whisper import WhisperModel  # 延遲載入，避免啟動變慢

    model = WhisperModel(config.WHISPER_MODEL, device="auto", compute_type="auto")
    seg_iter, info = model.transcribe(str(audio), vad_filter=True)
    segments = []
    for s in seg_iter:
        text = s.text.strip()
        if text:
            segments.append({"start": s.start, "end": s.end, "text": text})
        if on_progress and info.duration:
            on_progress(min(s.end / info.duration, 1.0))
    return info.language, segments
