"""設定與路徑。

路徑規則：
- BUNDLE_DIR：程式附帶的唯讀資源（static/）。開發時是專案根目錄；PyInstaller 打包後是解包目錄。
- DATA_DIR：使用者資料（.env、cache/、WebView 儲存）。
    1. 環境變數 TRANTUBE_DATA_DIR（最優先）
    2. 打包後：%LOCALAPPDATA%\\TubeTran（程式安裝位置通常不可寫）
    3. 開發時：專案根目錄（與過去的行為相同）
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

FROZEN = bool(getattr(sys, "frozen", False))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", _PROJECT_ROOT))


def resolve_data_dir() -> Path:
    env = os.getenv("TRANTUBE_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if FROZEN:
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        return Path(base) / "TubeTran"
    return _PROJECT_ROOT


DATA_DIR = resolve_data_dir()
load_dotenv(DATA_DIR / ".env")

CACHE_DIR = DATA_DIR / "cache"
STATIC_DIR = BUNDLE_DIR / "static"

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
