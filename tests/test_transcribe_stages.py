"""語音辨識的各階段與進度：讓使用者知道現在在做什麼（下載音檔 → 下載模型 → 載入模型 → 解碼音檔 → 辨識）。"""
from types import SimpleNamespace

import faster_whisper
import faster_whisper.utils
import huggingface_hub
import pytest

from tubetran import config, jobs
from tubetran.services import transcribe


def _fake_hf(monkeypatch, cached: bool, calls: list):
    def download_model(name, local_files_only=False, **kw):
        if local_files_only and not cached:
            raise huggingface_hub.errors.LocalEntryNotFoundError("not cached")
        return f"/cache/{name}"

    def snapshot_download(repo, allow_patterns=None, tqdm_class=None, **kw):
        calls.append((repo, allow_patterns))
        # huggingface_hub 把各檔案的下載位元組彙整到用 tqdm_class 建立、單位為 "B" 的進度條
        files = tqdm_class(total=4, desc="Fetching 4 files")
        bar = tqdm_class(unit="B", total=1000, desc="Downloading bytes")
        for n in (100, 400, 0, 500):
            bar.update(n)
        files.update(4)
        return f"/snap/{repo}"

    monkeypatch.setattr(faster_whisper.utils, "download_model", download_model)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)


def test_model_download_reports_real_byte_progress(monkeypatch):
    calls, started, progress = [], [], []
    _fake_hf(monkeypatch, cached=False, calls=calls)
    path = transcribe.ensure_model("small", lambda: started.append(1), progress.append)
    assert path == "/snap/Systran/faster-whisper-small"
    assert calls == [("Systran/faster-whisper-small", transcribe.MODEL_FILES)]  # 和 faster-whisper 下載同一組檔案
    assert started == [1]
    assert progress == [0.1, 0.5, 1.0]  # 只看位元組進度條、只增不減（檔案數的進度條不算）


def test_cached_model_is_used_without_downloading(monkeypatch):
    calls, started = [], []
    _fake_hf(monkeypatch, cached=True, calls=calls)
    assert transcribe.ensure_model("small", lambda: started.append(1)) == "/cache/small"
    assert calls == [] and started == []  # 已下載過：不會出現「下載模型」階段


def test_transcribe_reports_each_stage_in_order(monkeypatch, tmp_path):
    stages, progress = [], []
    monkeypatch.setattr(config, "WHISPER_MODEL", "small")

    def ensure_model(name, on_download=None, on_progress=None):
        on_download()
        on_progress(0.5)
        return "/model"

    class FakeModel:
        def __init__(self, path, **kw):
            assert path == "/model"  # 用 ensure_model 給的資料夾，不再讓 faster-whisper 自己下載

        def transcribe(self, audio, **kw):
            segs = [SimpleNamespace(start=0.0, end=5.0, text=" Bonjour. "), SimpleNamespace(start=5.0, end=10.0, text="")]
            return iter(segs), SimpleNamespace(language="fr", duration=10.0)

    monkeypatch.setattr(transcribe, "ensure_model", ensure_model)
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    lang, segs = transcribe.transcribe(tmp_path / "a.webm", progress.append, stages.append, lambda p: stages.append(p))
    assert lang == "fr" and segs == [{"start": 0.0, "end": 5.0, "text": "Bonjour."}]
    assert stages == ["downloading_model", 0.5, "loading_model", "preparing_audio", "transcribing"]
    assert progress == [0.5, 1.0]


def test_job_shows_each_stt_stage(monkeypatch, tmp_path):
    """背景任務把各階段與進度寫進 job，前端輪詢時才看得到。"""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    seen = []
    real_set = jobs._set
    monkeypatch.setattr(jobs, "_set", lambda job, stage, p=0.0: (seen.append((stage, round(p, 2))), real_set(job, stage, p)))
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles",
                        lambda vid: {"title": "T", "lang": "", "source": None, "segments": [], "duration": 10})

    def download_audio(vid, cache, check, on_progress=None):
        on_progress(0.4)
        on_progress(1.0)
        p = cache / "audio.webm"
        p.write_bytes(b"x")
        return p

    def fake_transcribe(audio, on_progress, on_stage, on_model_progress=None):
        on_stage("downloading_model")
        on_model_progress(0.3)
        on_stage("loading_model")
        on_stage("preparing_audio")
        on_stage("transcribing")
        on_progress(1.0)
        return "fr", [{"start": 0.0, "end": 5.0, "text": "Bonjour."}]

    monkeypatch.setattr(jobs.transcribe, "download_audio", download_audio)
    monkeypatch.setattr(jobs.transcribe, "transcribe", fake_transcribe)
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: {})
    monkeypatch.setattr(jobs.translate, "translate_segments", lambda segs, *a, **k: [{**s, "trans": "你好。"} for s in segs])
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: "T")
    job = jobs.Job("aaaaaaaaaaa")
    jobs._run(job)
    assert job.status == "done", job.error
    stt = [s for s in seen if s[0] in transcribe_stages()]
    assert stt == [("downloading_audio", 0.0), ("downloading_audio", 0.4), ("downloading_audio", 1.0),
                   ("downloading_model", 0.0), ("downloading_model", 0.3), ("loading_model", 0.0),
                   ("preparing_audio", 0.0), ("transcribing", 0.0), ("transcribing", 1.0)]


def transcribe_stages():
    return {"downloading_audio", "downloading_model", "loading_model", "preparing_audio", "transcribing"}


@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_every_stt_stage_has_texts(lang):
    """每個階段在中英文介面都有：進度卡片的標籤（lbl_）、階段清單（sub_）、影片庫卡片（stage_）。"""
    js = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    block = js.split("en: {")[0 if lang == "zh-TW" else 1]
    for s in transcribe_stages():
        for prefix in ("lbl_", "sub_", "stage_"):
            assert f"{prefix}{s}:" in block, f"{lang} 缺少 {prefix}{s}"
