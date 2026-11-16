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


def download_audio(
    video_id: str,
    out_dir: Path,
    check: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """下載音檔。check：下載過程中不斷呼叫，丟出例外就中止下載（用來取消任務）。
    on_progress：下載進度（0～1），yt-dlp 知道檔案大小時才會回報。

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
    def hook(d: dict) -> None:
        if check:
            check()
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if on_progress and total and d.get("downloaded_bytes") is not None:
            on_progress(min(d["downloaded_bytes"] / total, 1.0))

    opts["progress_hooks"] = [hook]
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


# faster-whisper 下載模型時用的檔案清單（同 faster_whisper.utils.download_model）
MODEL_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def _byte_progress_class(on_progress: Callable[[float], None]):
    """給 huggingface_hub.snapshot_download 的 tqdm_class：它會把各檔案的下載位元組彙整到用這個類別建立的
    進度條（單位 "B"）。我們不在主控台畫進度條，只把比例回報出去（只增不減）。"""
    import io

    from tqdm.auto import tqdm

    best = [0.0]

    class Reporter(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["file"] = io.StringIO()
            self._bytes = kwargs.get("unit") == "B"
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            super().update(n)
            if self._bytes and self.total:
                frac = min(self.n / self.total, 1.0)
                if frac > best[0]:
                    best[0] = frac
                    on_progress(frac)

    return Reporter


def ensure_model(
    name: str,
    on_download: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    """回傳語音辨識模型的資料夾。已下載過就直接用；沒有的話下載（第一次使用 small 約 460 MB），
    下載前呼叫 on_download，下載中以 on_progress 回報進度（0～1）。

    下載和 faster_whisper.download_model 相同（同一個 repo、同一組檔案、同一個快取位置），差別只在
    傳入會回報進度的 tqdm_class（faster-whisper 傳的是關掉的進度條，拿不到進度）。"""
    from faster_whisper.utils import _MODELS, download_model
    from huggingface_hub import snapshot_download

    try:
        return download_model(name, local_files_only=True)
    except Exception:  # noqa: BLE001 — 還沒下載，或快取不完整
        pass
    if on_download:
        on_download()
    repo = name if "/" in name else _MODELS.get(name)
    if repo is None:  # 不認得的名稱：交給 faster-whisper 處理（它會丟出清楚的錯誤訊息）
        return download_model(name)
    kwargs = {"allow_patterns": MODEL_FILES}
    if on_progress:
        kwargs["tqdm_class"] = _byte_progress_class(on_progress)
    return snapshot_download(repo, **kwargs)


def transcribe(
    audio: Path,
    on_progress: Callable[[float], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
    on_model_progress: Callable[[float], None] | None = None,
) -> tuple[str, list[dict]]:
    """回傳 (偵測到的語言, segments)。

    on_stage：進入各階段時呼叫，讓使用者知道現在在做什麼（辨識前的準備可能要好一陣子）：
      downloading_model（只有模型還沒下載過時）→ loading_model → preparing_audio → transcribing
    on_model_progress：下載模型的進度（0～1）。
    """
    from faster_whisper import WhisperModel  # 延遲載入，避免啟動變慢

    stage = on_stage or (lambda _s: None)
    model_path = ensure_model(config.WHISPER_MODEL, lambda: stage("downloading_model"), on_model_progress)
    stage("loading_model")
    model = WhisperModel(model_path, device="auto", compute_type="auto")
    stage("preparing_audio")  # 解碼整個音檔、偵測語言：長影片要一段時間才會開始辨識
    seg_iter, info = model.transcribe(str(audio), vad_filter=True)
    stage("transcribing")
    segments = []
    for s in seg_iter:
        text = s.text.strip()
        if text:
            segments.append({"start": s.start, "end": s.end, "text": text})
        if on_progress and info.duration:
            on_progress(min(s.end / info.duration, 1.0))
    return info.language, segments
