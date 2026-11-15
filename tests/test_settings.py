import pytest
from fastapi.testclient import TestClient

from tubetran import config, settings
from tubetran.main import app

KEY = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ-0123456789xy"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """資料資料夾指到暫存目錄；設定值全部用 monkeypatch，測完自動還原。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "ENV_LOCKED", frozenset())
    monkeypatch.setattr(config, "TRANSLATE_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(config, "WHISPER_MODEL", "small")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    for n in ("TRANSLATE_MODEL", "WHISPER_MODEL"):
        monkeypatch.delenv(n, raising=False)
    with TestClient(app) as c:
        yield c


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


def test_put_updates_env_file_and_runtime(client, tmp_path):
    new_key = "sk-ant-NEWKEY-1234567890"
    r = client.put("/api/settings", json={"api_key": new_key, "translate_model": "claude-sonnet-5-5", "whisper_model": "medium"})
    assert r.status_code == 200 and new_key not in r.text
    assert config.get_api_key() == new_key
    assert config.TRANSLATE_MODEL == "claude-sonnet-5-5" and config.WHISPER_MODEL == "medium"
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"ANTHROPIC_API_KEY={new_key}" in env
    assert "TRANSLATE_MODEL=claude-sonnet-5-5" in env and "WHISPER_MODEL=medium" in env


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
    assert config.get_api_key() == KEY and not (tmp_path / ".env").exists()


def test_env_var_takes_priority_and_cannot_be_changed_in_ui(client, monkeypatch):
    monkeypatch.setattr(config, "ENV_LOCKED", frozenset({"ANTHROPIC_API_KEY", "WHISPER_MODEL"}))
    assert client.get("/api/settings").json()["locked"] == {
        "api_key": True, "translate_model": False, "whisper_model": True}
    assert client.put("/api/settings", json={"api_key": "sk-other"}).status_code == 400
    assert client.put("/api/settings", json={"whisper_model": "medium"}).status_code == 400
    assert config.get_api_key() == KEY and config.WHISPER_MODEL == "small"
    # 沿用目前值（前端一律會送）不算修改；沒鎖的項目照常更新
    r = client.put("/api/settings", json={"whisper_model": "small", "translate_model": "claude-sonnet-5-5"})
    assert r.status_code == 200 and config.TRANSLATE_MODEL == "claude-sonnet-5-5"


def test_dotenv_does_not_override_existing_environment(tmp_path, monkeypatch):
    """load_dotenv 預設不覆蓋已存在的環境變數：環境變數 > .env 的優先順序依賴這個行為。"""
    from dotenv import load_dotenv

    (tmp_path / ".env").write_text("TUBETRAN_TEST_VAR=from-file\n", encoding="utf-8")
    monkeypatch.setenv("TUBETRAN_TEST_VAR", "from-env")
    load_dotenv(tmp_path / ".env")
    import os
    assert os.environ["TUBETRAN_TEST_VAR"] == "from-env"


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

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/models").json()["translate"]["error"] == "no_key"

    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    resp = httpx.Response(401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))
    _fake_anthropic(monkeypatch, exc=anthropic.AuthenticationError("bad", response=resp, body=None))
    assert client.get("/api/models").json()["translate"]["error"] == "auth"

    _fake_anthropic(monkeypatch, exc=RuntimeError("boom"))
    t = client.get("/api/models").json()["translate"]
    assert t["error"] == "failed" and "boom" not in str(t)


def test_server_starts_and_process_asks_for_key_when_missing(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/api/settings").json()["has_key"] is False
    r = client.post("/api/process", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
