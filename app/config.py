"""讀取 .env 設定。"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "cache"
STATIC_DIR = ROOT / "static"

TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL", "claude-haiku-5-5")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
BATCH_SIZE = int(os.getenv("TRANSLATE_BATCH_SIZE", "50"))


def get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "找不到 ANTHROPIC_API_KEY，請在專案根目錄的 .env 設定（可參考 .env.example）。"
        )
    return key
