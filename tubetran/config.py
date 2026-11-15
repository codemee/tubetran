"""設定與路徑。

路徑規則：
- STATIC_DIR：程式附帶的唯讀前端檔，放在套件內的 tubetran/static/（安裝、打包後都跟著套件走）。
- DATA_DIR：使用者資料（settings.json、cache/、WebView 儲存）。
    1. 環境變數 TUBETRAN_DATA_DIR（最優先）
    2. 從原始碼資料夾執行（專案根目錄有 pyproject.toml）：專案根目錄
    3. 其他（uv tool install 安裝後、PyInstaller 打包後）：使用者資料目錄
       Windows %LOCALAPPDATA%\\TubeTran；macOS ~/Library/Application Support/TubeTran；
       Linux $XDG_DATA_HOME/TubeTran 或 ~/.local/share/TubeTran
"""
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

FROZEN = bool(getattr(sys, "frozen", False))
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent


def _is_source_checkout() -> bool:
    """tubetran 套件是否直接位在原始碼資料夾（而不是 site-packages）。"""
    return not FROZEN and (_PROJECT_ROOT / "pyproject.toml").is_file()


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "TubeTran"


def resolve_data_dir() -> Path:
    env = os.getenv("TUBETRAN_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if _is_source_checkout():
        return _PROJECT_ROOT
    return user_data_dir()


DATA_DIR = resolve_data_dir()
SETTINGS_FILENAME = "settings.json"

# 設定的優先順序（高 → 低）：
#   1. 作業系統的環境變數
#   2. 設定面板儲存的 settings.json
#   3. 舊式的 .env（只讀；保留給舊使用者與開發，程式不會再寫入）
#   4. 內建預設值
# 啟動時就已由環境變數指定的項目，介面不能改（改了也不會生效），所以先記下來。
SETTING_NAMES = ("ANTHROPIC_API_KEY", "TRANSLATE_MODEL", "WHISPER_MODEL")
ENV_LOCKED = frozenset(n for n in SETTING_NAMES if os.environ.get(n, "").strip())


def read_settings_file(path: Path | None = None) -> dict:
    """讀 settings.json；不存在或內容壞掉就當成空的（不讓啟動因此失敗）。"""
    try:
        data = json.loads((path or DATA_DIR / SETTINGS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_legacy_env() -> dict:
    p = DATA_DIR / ".env"
    return {k: v for k, v in dotenv_values(p).items() if v} if p.is_file() else {}


USER_SETTINGS = read_settings_file()  # 設定面板儲存的值（儲存時會同步更新這份記憶體副本）
_LEGACY_ENV = _read_legacy_env()


def _resolve(env_name: str, json_key: str | None, default: str) -> str:
    for v in (
        os.environ.get(env_name),
        USER_SETTINGS.get(json_key) if json_key else None,
        _LEGACY_ENV.get(env_name),
    ):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


CACHE_DIR = DATA_DIR / "cache"
STATIC_DIR = _PACKAGE_DIR / "static"

TRANSLATE_MODEL = _resolve("TRANSLATE_MODEL", "translate_model", "claude-haiku-5-5")
WHISPER_MODEL = _resolve("WHISPER_MODEL", "whisper_model", "small")
BATCH_SIZE = int(_resolve("TRANSLATE_BATCH_SIZE", None, "50"))


def current_api_key() -> str:
    """目前的 API 金鑰（沒有就回空字串）。每次呼叫都重新依優先順序查，環境變數隨時生效。"""
    return _resolve("ANTHROPIC_API_KEY", "api_key", "")


def get_api_key() -> str:
    key = current_api_key()
    if not key:
        raise RuntimeError(
            "尚未設定 ANTHROPIC_API_KEY：請按右上角的設定鈕輸入，或設定同名的環境變數"
            f"（設定檔：{DATA_DIR / SETTINGS_FILENAME}）。"
        )
    return key
