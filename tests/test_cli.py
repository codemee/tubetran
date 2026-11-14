import sys
from pathlib import Path

import pytest

from tubetran import cli, config


def test_defaults_are_desktop_mode():
    a = cli.build_parser().parse_args([])
    assert a.server is False and a.host == "127.0.0.1" and a.port == 8000


def test_server_options():
    a = cli.build_parser().parse_args(["--server", "--host", "0.0.0.0", "--port", "9000"])
    assert a.server is True and a.host == "0.0.0.0" and a.port == 9000


def test_invalid_port_exits_with_code_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(["--port", "abc"])
    assert e.value.code == 2


def test_desktop_port_is_stable_then_falls_back_when_busy():
    # 固定埠讓 localStorage 的來源在每次啟動都相同；被占用時才退回隨機埠
    assert cli._pick_port() == cli.DESKTOP_PORT
    import socket
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", cli.DESKTOP_PORT))
        other = cli._pick_port()
        assert other != cli.DESKTOP_PORT and 1024 < other < 65536


def test_app_icon_is_a_valid_multi_size_ico():
    """視窗標題列與執行檔共用同一個 .ico；至少要有標題列(16)與工作列(32)用的尺寸。"""
    data = (config.STATIC_DIR / "logo" / "tubetran.ico").read_bytes()
    reserved, kind, count = int.from_bytes(data[0:2], "little"), int.from_bytes(data[2:4], "little"), int.from_bytes(data[4:6], "little")
    assert (reserved, kind) == (0, 1) and count >= 3
    sizes = {(data[6 + 16 * i] or 256) for i in range(count)}
    assert {16, 32} <= sizes


def test_data_dir_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("TUBETRAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "FROZEN", True)
    assert config.resolve_data_dir() == tmp_path.resolve()


def test_data_dir_frozen_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("TUBETRAN_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(sys, "platform", "win32")
    assert config.resolve_data_dir() == tmp_path / "TubeTran"


def test_data_dir_installed_package_uses_user_data_dir(tmp_path, monkeypatch):
    """uv tool install 之後 tubetran 套件在 site-packages（旁邊沒有 pyproject.toml），資料不能寫進去。"""
    monkeypatch.delenv("TUBETRAN_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "FROZEN", False)
    monkeypatch.setattr(config, "_PROJECT_ROOT", tmp_path / "site-packages")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config.resolve_data_dir() == tmp_path / "xdg" / "TubeTran"


def test_user_data_dir_per_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert config.user_data_dir() == tmp_path / "Library" / "Application Support" / "TubeTran"
    monkeypatch.setattr(sys, "platform", "linux")
    assert config.user_data_dir() == tmp_path / ".local" / "share" / "TubeTran"


def test_data_dir_dev_is_project_root(monkeypatch):
    monkeypatch.delenv("TUBETRAN_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "FROZEN", False)
    assert config.resolve_data_dir() == Path(config.__file__).resolve().parent.parent


def test_missing_api_key_message_points_to_env_file(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        config.get_api_key()
    assert str(config.DATA_DIR / ".env") in str(e.value)
