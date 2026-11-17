"""桌面版的下載（另存新檔）：WebView 預設不允許下載，匯出檔與 SRT／VTT 由桌面版跳出對話框後寫入。"""
import io
import json
import urllib.error
import urllib.request

import pytest

from tubetran import cli


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, disposition: str):
        super().__init__(body)
        self.headers = {"Content-Disposition": disposition}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def api(monkeypatch, tmp_path):
    a = cli._DesktopApi()
    a._port = 47321
    dialogs = []

    class Window:
        def create_file_dialog(self, kind, save_filename=""):
            dialogs.append((kind, save_filename))
            return a._chosen

    a._window = Window()
    a._chosen = str(tmp_path / "out.json")
    fetched = []

    def urlopen(url, timeout=0):
        fetched.append(url)
        return FakeResponse(b'{"ok": 1}', 'attachment; filename="tubetran-20261117-2.json"')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)  # save_download 執行時才 import urllib.request
    return a, dialogs, fetched, tmp_path


def test_saves_export_to_the_chosen_file(api):
    a, dialogs, fetched, tmp_path = api
    r = a.save_download("/api/export?ids=aaaaaaaaaaa,bbbbbbbbbbb")
    assert r == {"saved": str(tmp_path / "out.json")}
    assert fetched == ["http://127.0.0.1:47321/api/export?ids=aaaaaaaaaaa,bbbbbbbbbbb"]  # 向自己的後端取得
    assert dialogs[0][1] == "tubetran-20261117-2.json"  # 對話框預設檔名＝後端給的檔名
    assert (tmp_path / "out.json").read_bytes() == b'{"ok": 1}'


def test_chinese_file_name_from_rfc5987_header():
    """中文檔名放在 filename*（UTF-8）；對話框的預設檔名要用它，而不是 ASCII 的備用名稱。"""
    disp = "attachment; filename=\" Docker.json\"; filename*=UTF-8''Docker%20%E5%AE%B9%E5%99%A8.json"
    assert cli.download_filename(disp) == "Docker 容器.json"
    assert cli.download_filename('attachment; filename="a.srt"') == "a.srt"
    assert cli.download_filename("") == "tubetran-download"


def test_subtitle_downloads_are_allowed_too(api):
    a, _, fetched, _ = api
    assert "saved" in a.save_download("/api/subtitles/aaaaaaaaaaa.srt?mode=both")
    assert "saved" in a.save_download("/api/subtitles/aaaaaaaaaaa.vtt")


def test_only_our_own_download_urls_are_accepted(api):
    """不能被拿來從網路下載任意東西、或讀取後端其他資料。"""
    a, dialogs, fetched, _ = api
    for bad in ("https://evil.example/x", "/api/settings", "/api/export/../settings", "//evil.example/api/export",
                "/api/subtitles/../../x.srt", "/api/export?ids=a&x=1"):
        assert a.save_download(bad) == {"error": "不支援的下載"}, bad
    assert fetched == [] and dialogs == []


def test_cancelling_the_dialog_writes_nothing(api):
    a, _, _, tmp_path = api
    a._chosen = None
    assert a.save_download("/api/export") == {"cancelled": True}
    assert not (tmp_path / "out.json").exists()


def test_server_error_is_reported_without_a_dialog(api, monkeypatch):
    a, dialogs, _, _ = api

    def urlopen(url, timeout=0):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(json.dumps({"detail": "沒有可以匯出的影片"}).encode()))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert a.save_download("/api/export") == {"error": "沒有可以匯出的影片"}
    assert dialogs == []
