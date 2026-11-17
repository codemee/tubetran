"""yt-dlp 的共用設定與音檔下載重試。"""
import pytest
import yt_dlp

from tubetran.services import subtitles, transcribe, ytdl


def test_uses_whichever_js_runtime_is_installed(monkeypatch):
    found = {"node": r"C:\nodejs\node.exe"}
    monkeypatch.setattr(ytdl.shutil, "which", lambda name: found.get(name))
    assert ytdl.js_runtimes() == {"node": {"path": r"C:\nodejs\node.exe"}}
    assert ytdl.base_opts()["js_runtimes"] == {"node": {"path": r"C:\nodejs\node.exe"}}
    # 都沒有：不指定（yt-dlp 照舊運作，只是偶爾會 403）
    monkeypatch.setattr(ytdl.shutil, "which", lambda name: None)
    assert "js_runtimes" not in ytdl.base_opts()


def test_subtitle_fetch_uses_the_shared_options(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {"title": "T", "language": "en"}

    monkeypatch.setattr(ytdl, "js_runtimes", lambda: {"deno": {"path": "deno"}})
    monkeypatch.setattr(subtitles.yt_dlp, "YoutubeDL", FakeYDL)
    subtitles.fetch_subtitles("aaaaaaaaaaa")
    assert seen["js_runtimes"] == {"deno": {"path": "deno"}} and seen["skip_download"] is True


def _fake_downloader(fail_times: int, calls: list):
    class FakeYDL:
        def __init__(self, opts):
            self.out = opts["outtmpl"].replace("%(ext)s", "webm")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            calls.append(urls[0])
            if len(calls) <= fail_times:
                open(self.out + ".part", "wb").write(b"half")  # 下載到一半被擋：留下 .part
                raise yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
            open(self.out, "wb").write(b"audio")

    return FakeYDL


def test_audio_download_retries_after_403(tmp_path, monkeypatch):
    """回歸：gKDnMEsYOWs 下載音檔偶發 HTTP 403，整個任務就失敗。要重新取得網址再試。"""
    calls = []
    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", _fake_downloader(2, calls))
    monkeypatch.setattr(ytdl, "RETRY_WAIT", 0)
    path = transcribe.download_audio("gKDnMEsYOWs", tmp_path)
    assert len(calls) == 3 and path.name == "audio.webm"  # .part 不能被當成下載完成的音檔


def test_audio_download_gives_up_after_the_last_attempt(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", _fake_downloader(99, calls))
    monkeypatch.setattr(ytdl, "RETRY_WAIT", 0)
    with pytest.raises(yt_dlp.utils.DownloadError):
        transcribe.download_audio("gKDnMEsYOWs", tmp_path)
    assert len(calls) == ytdl.DOWNLOAD_ATTEMPTS


def test_cancel_during_retry_wait_stops_immediately(tmp_path, monkeypatch):
    class Cancelled(Exception):
        pass

    calls = []
    monkeypatch.setattr(ytdl.yt_dlp, "YoutubeDL", _fake_downloader(99, calls))
    monkeypatch.setattr(ytdl, "RETRY_WAIT", 0)

    def check():
        raise Cancelled

    with pytest.raises(Cancelled):
        transcribe.download_audio("gKDnMEsYOWs", tmp_path, check)
    assert len(calls) == 1  # 第一次失敗後就發現已被取消，不再重試

