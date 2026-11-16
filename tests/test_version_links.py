import tomllib
from pathlib import Path

import pytest

import tubetran
from tubetran import cli, settings

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject():
    # 版本號的唯一來源是 pyproject.toml；已安裝時 metadata 必須與它一致（升版後忘了 uv lock 也會被抓到）
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert tubetran.__version__ == declared


def test_settings_include_version():
    assert settings.current()["version"] == tubetran.__version__


def test_version_flag_prints_version_and_exits(capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(["--version"])
    assert e.value.code == 0
    assert tubetran.__version__ in capsys.readouterr().out


def test_open_external_only_allows_youtube_and_project_github(monkeypatch):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    api = cli._DesktopApi()
    assert api.open_external("https://www.youtube.com/watch?v=hO-i1l8BecM") is True
    assert api.open_external("https://github.com/codemee/tubetran/releases") is True
    assert api.open_external("file:///C:/Windows/System32/calc.exe") is False
    assert api.open_external("https://evil.example/https://www.youtube.com/watch?v=x") is False
    assert api.open_external("https://www.youtube.com.evil.example/watch?v=x") is False
    assert opened == ["https://www.youtube.com/watch?v=hO-i1l8BecM", "https://github.com/codemee/tubetran/releases"]
