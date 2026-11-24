import json

import pytest
from fastapi.testclient import TestClient

from tubetran import config, settings
from tubetran.main import app

KEY = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789xy"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """資料資料夾指到暫存目錄；設定值全部用 monkeypatch，測完自動還原。
    起始狀態：沒有任何環境變數，金鑰存在 settings.json（USER_SETTINGS）。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "ENV_LOCKED", frozenset())
    monkeypatch.setattr(config, "USER_SETTINGS", {"api_key": KEY})
    monkeypatch.setattr(config, "_LEGACY_ENV", {})
    monkeypatch.setattr(config, "TRANSLATE_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(config, "WHISPER_MODEL", "small")
    for n in config.SETTING_NAMES:
        monkeypatch.delenv(n, raising=False)
    with TestClient(app) as c:
        yield c


def _file(tmp_path) -> dict:
    return json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))


def test_mask_key_shows_only_first_and_last_two():
    m = settings.mask_key(KEY)
    assert m.startswith("sk") and m.endswith("xy") and set(m[2:-2]) == {"*"}
    assert KEY not in m and len(m) == 2 + settings.MAX_STARS + 2  # 長金鑰的星號數有上限
    assert settings.mask_key("abcdef") == "ab**ef"
    assert settings.mask_key("abcd") == "****" and settings.mask_key("") == ""


def test_get_settings_never_returns_the_full_key(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert KEY not in r.text and body["api_key"].startswith("sk") and body["has_key"] is True
    assert body["translate_model"] == "claude-haiku-5-5" and body["whisper_model"] == "small"
    assert body["locked"] == {"api_key": False, "translate_model": False, "whisper_model": False}


def test_put_updates_settings_file_and_runtime(client, tmp_path):
    new_key = "sk-ant-NEWKEY-1234567890"
    r = client.put("/api/settings", json={"api_key": new_key, "translate_model": "claude-sonnet-5-5", "whisper_model": "medium"})
    assert r.status_code == 200 and new_key not in r.text
    assert config.get_api_key() == new_key
    assert config.TRANSLATE_MODEL == "claude-sonnet-5-5" and config.WHISPER_MODEL == "medium"
    assert _file(tmp_path) == {"api_key": new_key, "translate_model": "claude-sonnet-5-5", "whisper_model": "medium"}
    assert not (tmp_path / "settings.json.tmp").exists() and not (tmp_path / ".env").exists()


def test_put_keeps_unknown_fields_already_in_the_file(client, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"api_key": KEY, "extra": 1}), encoding="utf-8")
    client.put("/api/settings", json={"whisper_model": "base"})
    assert _file(tmp_path) == {"api_key": KEY, "extra": 1, "whisper_model": "base"}


def test_put_without_key_keeps_existing_key(client):
    r = client.put("/api/settings", json={"api_key": "", "whisper_model": "base"})
    assert r.status_code == 200 and config.get_api_key() == KEY and config.WHISPER_MODEL == "base"


@pytest.mark.parametrize("body", [
    {"api_key": "has space"},
    {"api_key": "line\nbreak"},
    {"translate_model": "bad model!"},
    {"translate_model": ""},
    {"whisper_model": "not-a-real-model"},
])
def test_put_rejects_invalid_values(client, body, tmp_path):
    r = client.put("/api/settings", json=body)
    assert r.status_code == 400
    assert config.get_api_key() == KEY and not (tmp_path / "settings.json").exists()


def test_env_var_takes_priority_and_cannot_be_changed_in_ui(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("WHISPER_MODEL", "small")
    monkeypatch.setattr(config, "ENV_LOCKED", frozenset({"ANTHROPIC_API_KEY", "WHISPER_MODEL"}))
    assert client.get("/api/settings").json()["locked"] == {
        "api_key": True, "translate_model": False, "whisper_model": True}
    assert client.put("/api/settings", json={"api_key": "sk-other"}).status_code == 400
    assert client.put("/api/settings", json={"whisper_model": "medium"}).status_code == 400
    assert config.get_api_key() == KEY and config.WHISPER_MODEL == "small"
    # 沿用目前值（前端一律會送）不算修改；沒鎖的項目照常更新
    r = client.put("/api/settings", json={"whisper_model": "small", "translate_model": "claude-sonnet-5-5"})
    assert r.status_code == 200 and config.TRANSLATE_MODEL == "claude-sonnet-5-5"


def test_priority_env_over_settings_file_over_legacy_dotenv(monkeypatch):
    monkeypatch.setattr(config, "USER_SETTINGS", {"api_key": "from-json"})
    monkeypatch.setattr(config, "_LEGACY_ENV", {"ANTHROPIC_API_KEY": "from-dotenv", "TRANSLATE_MODEL": "legacy-model"})
    for n in config.SETTING_NAMES:
        monkeypatch.delenv(n, raising=False)
    assert config.current_api_key() == "from-json"                      # settings.json > .env
    assert config._resolve("TRANSLATE_MODEL", "translate_model", "d") == "legacy-model"  # 只有 .env 有
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert config.current_api_key() == "from-env"                       # 環境變數最優先
    monkeypatch.setattr(config, "USER_SETTINGS", {})
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert config.current_api_key() == "from-dotenv"                    # 舊式 .env 仍可用
    monkeypatch.setattr(config, "_LEGACY_ENV", {})
    assert config._resolve("WHISPER_MODEL", "whisper_model", "small") == "small"  # 都沒有 → 預設值


def test_settings_file_corrupt_or_wrong_type_is_ignored(tmp_path):
    p = tmp_path / "settings.json"
    assert config.read_settings_file(p) == {}                           # 不存在
    p.write_text("{not json", encoding="utf-8")
    assert config.read_settings_file(p) == {}                           # 壞掉
    p.write_text("[1, 2]", encoding="utf-8")
    assert config.read_settings_file(p) == {}                           # 不是物件
    p.write_text('{"api_key": "k"}', encoding="utf-8")
    assert config.read_settings_file(p) == {"api_key": "k"}


def test_legacy_dotenv_is_read_but_never_written(client, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=legacy\n", encoding="utf-8")
    before = (tmp_path / ".env").read_text(encoding="utf-8")
    client.put("/api/settings", json={"api_key": "sk-ant-NEW-1234567890", "whisper_model": "base"})
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before   # 程式不再改寫 .env
    assert _file(tmp_path)["api_key"] == "sk-ant-NEW-1234567890"        # 新值在 settings.json，優先於 .env


def test_write_failure_leaves_runtime_state_unchanged(client, monkeypatch):
    def boom(values):
        raise OSError("disk full")

    monkeypatch.setattr(settings, "_write_file", boom)
    r = client.put("/api/settings", json={"api_key": "sk-ant-NEW-1234567890", "whisper_model": "base"})
    assert r.status_code == 500
    assert config.get_api_key() == KEY and config.WHISPER_MODEL == "small"


def test_frontend_files_must_be_revalidated_so_upgrades_are_not_shadowed_by_a_stale_cache(client):
    """桌面版 WebView 的快取存在資料資料夾；沒有 Cache-Control 時瀏覽器會自己猜可以快取多久，
    升級後可能繼續用舊的 JS／CSS（實測過：視窗載入的 desktop.js 是舊版，伺服器上已是新版）。"""
    for path in ("/", "/static/app.js", "/static/desktop.js", "/static/style.css", "/static/logo/tubetran-light-icon.svg", "/favicon.ico"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    # 沒變就回 304（用 ETag 重新確認），標頭仍然在
    first = client.get("/static/app.js")
    again = client.get("/static/app.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["cache-control"] == "no-cache"


def test_index_references_versioned_asset_urls(client, tmp_path, monkeypatch):
    """舊版本已存進 WebView 快取的檔案不能再被用到：腳本與樣式表的網址要帶內容版本，檔案一變網址就變。"""
    import re
    import shutil

    static = tmp_path / "static"
    shutil.copytree(config.STATIC_DIR, static)
    monkeypatch.setattr(config, "STATIC_DIR", static)

    def urls():
        html = client.get("/").text
        return re.findall(r'(?:src|href)="(/static/[^"]+\.(?:js|css)\?v=[0-9a-f]{10})"', html), html

    first, html = urls()
    names = {u.split("?v=")[0] for u in first}
    assert names == {"/static/style.css", "/static/i18n.js", "/static/fsbutton.js", "/static/linebreak.js", "/static/search.js", "/static/subpos.js", "/static/app.js",
                     "/static/glossary.js", "/static/settings.js", "/static/desktop.js"}
    assert 'href="/static/logo/tubetran-light-icon.svg"' in html  # 圖片不需要
    assert len({u.split("?v=")[1] for u in first}) == 1            # 同一版本的檔案共用同一個版本字串
    assert urls()[0] == first                                      # 沒改檔案：版本不變（才有快取效果）
    (static / "app.js").write_text("// changed\n", encoding="utf-8")
    assert urls()[0] != first                                      # 改了檔案：網址就變


def test_whisper_models_match_faster_whisper_official_list(client):
    from faster_whisper.utils import available_models

    got = client.get("/api/models").json()["whisper"]
    assert got == list(available_models()) and {"tiny", "small", "large-v3", "turbo"} <= set(got)


class _Model:
    def __init__(self, id, display_name):
        self.id, self.display_name = id, display_name


def _fake_anthropic(monkeypatch, models=None, exc=None):
    import anthropic

    class _Models:
        def list(self, limit=20):
            if exc:
                raise exc
            return iter(models)

    class _Client:
        def __init__(self, **kw):
            self.models = _Models()

    monkeypatch.setattr(anthropic, "Anthropic", _Client)


def test_translate_models_come_from_the_api_and_only_claude(client, monkeypatch):
    _fake_anthropic(monkeypatch, [_Model("claude-sonnet-5-5", "Claude Sonnet 5.5"), _Model("other-model", "X")])
    t = client.get("/api/models").json()["translate"]
    assert t == {"models": [{"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"}], "error": None}


def test_translate_models_error_codes(client, monkeypatch):
    import anthropic
    import httpx

    monkeypatch.setattr(config, "USER_SETTINGS", {})
    assert client.get("/api/models").json()["translate"]["error"] == "no_key"

    monkeypatch.setattr(config, "USER_SETTINGS", {"api_key": KEY})
    resp = httpx.Response(401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))
    _fake_anthropic(monkeypatch, exc=anthropic.AuthenticationError("bad", response=resp, body=None))
    assert client.get("/api/models").json()["translate"]["error"] == "auth"

    _fake_anthropic(monkeypatch, exc=RuntimeError("boom"))
    t = client.get("/api/models").json()["translate"]
    assert t["error"] == "failed" and "boom" not in str(t)


def test_server_starts_and_process_asks_for_key_when_missing(client, monkeypatch):
    monkeypatch.setattr(config, "USER_SETTINGS", {})
    assert client.get("/api/settings").json()["has_key"] is False
    r = client.post("/api/process", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
