"""設定與路徑。

路徑規則：
- STATIC_DIR：程式附帶的唯讀前端檔，放在套件內的 tubetran/static/（安裝、打包後都跟著套件走）。
- DATA_DIR：使用者資料（.env、cache/、WebView 儲存）。
    1. 環境變數 TUBETRAN_DATA_DIR（最優先）
    2. 從原始碼資料夾執行（專案根目錄有 pyproject.toml）：專案根目錄
    3. 其他（uv tool install 安裝後、PyInstaller 打包後）：使用者資料目錄
       Windows %LOCALAPPDATA%\\TubeTran；macOS ~/Library/Application Support/TubeTran；
       Linux $XDG_DATA_HOME/TubeTran 或 ~/.local/share/TubeTran
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

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
load_dotenv(DATA_DIR / ".env")

CACHE_DIR = DATA_DIR / "cache"
STATIC_DIR = _PACKAGE_DIR / "static"

TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", "claude-haiku-5-5")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
BATCH_SIZE = int(os.getenv("TRANSLATE_BATCH_SIZE", "50"))


def get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            f"找不到 ANTHROPIC_API_KEY，請在 {DATA_DIR / '.env'} 設定（可參考 .env.example）。"
        )
    return key
