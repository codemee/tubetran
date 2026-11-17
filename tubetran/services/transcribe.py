"""無字幕時：下載音檔，再用本機 faster-whisper 轉成文字。"""
from pathlib import Path
from typing import Callable

from tubetran import config
from tubetran.services import ytdl


def download_audio(
    video_id: str,
    out_dir: Path,
    check: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """下載音檔（存成 audio.*）。重試、取消與進度見 ytdl.download_media。"""
    path = ytdl.download_media(video_id, out_dir, "audio", "bestaudio/best", check, on_progress)
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
