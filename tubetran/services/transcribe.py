"""無字幕時：下載音檔，再用本機 faster-whisper 轉成文字。"""
import time
from pathlib import Path
from typing import Callable

import yt_dlp

from tubetran import config
from tubetran.services import ytdl

DOWNLOAD_ATTEMPTS = 3
RETRY_WAIT = 2.0  # 秒；每次重試多等一點


def _done_audio(out_dir: Path) -> Path | None:
    """已下載完成的音檔（不含下載到一半的 .part 等暫存檔）。"""
    return next((p for p in out_dir.glob("audio.*") if p.suffix not in (".part", ".ytdl", ".tmp")), None)


def download_audio(video_id: str, out_dir: Path, check: Callable[[], None] | None = None) -> Path:
    """下載音檔。check：下載過程中不斷呼叫，丟出例外就中止下載（用來取消任務）。

    YouTube 偶爾會在下載途中回 HTTP 403（電腦上沒有 JS 執行環境時尤其常見，見 ytdl.py）。
    每次重試都重新向 YouTube 取得下載網址，通常第二次就會成功。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = _done_audio(out_dir)
    if existing:
        return existing
    opts = {
        **ytdl.base_opts(),
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "audio.%(ext)s"),
    }
    if check:
        opts["progress_hooks"] = [lambda _d: check()]
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            break
        except yt_dlp.utils.DownloadError:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            if check:
                check()  # 等待前先看看是不是已被取消
            time.sleep(RETRY_WAIT * attempt)
    path = _done_audio(out_dir)
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
