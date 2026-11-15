"""可在介面調整的設定：API 金鑰、翻譯模型、語音辨識（STT）模型。

儲存在資料資料夾的 .env（與手動編輯同一份檔案），同時更新目前程序的環境變數與 config，
所以改完立刻對「之後開始的任務」生效，不必重啟。
"""
import re
from pathlib import Path

from dotenv import set_key

from tubetran import config

MAX_STARS = 20
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


def mask_key(key: str) -> str:
    """只顯示頭尾各兩碼，中間以 * 取代（星號最多 MAX_STARS 個，避免畫面被一長串星號撐開）。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return "*" * len(key)
    return key[:2] + "*" * min(len(key) - 4, MAX_STARS) + key[-2:]


def whisper_models() -> list[str]:
    """faster-whisper 官方支援的模型名稱（faster_whisper.utils._MODELS，與其 GitHub 原始碼一致）。"""
    from faster_whisper.utils import available_models

    return list(available_models())


def current() -> dict:
    """回給前端的設定：金鑰只回遮罩後的字串，絕不回傳完整金鑰。"""
    key = config.current_api_key()
    return {
        "has_key": bool(key),
        "api_key": mask_key(key),
        "translate_model": config.TRANSLATE_MODEL,
        "whisper_model": config.WHISPER_MODEL,
        # 由作業系統環境變數指定的項目：優先於 .env，介面只能顯示、不能改
        "locked": {
            "api_key": "ANTHROPIC_API_KEY" in config.ENV_LOCKED,
            "translate_model": "TRANSLATE_MODEL" in config.ENV_LOCKED,
            "whisper_model": "WHISPER_MODEL" in config.ENV_LOCKED,
        },
    }


def validate(api_key: str | None, translate_model: str | None, whisper_model: str | None) -> None:
    """不合法就丟 ValueError（訊息是給使用者看的）。"""
    if api_key is not None and api_key.strip():
        k = api_key.strip()
        if len(k) > 300 or re.search(r"\s", k) or not k.isascii():
            raise ValueError("API 金鑰格式不正確（不能有空白或換行）")
    if translate_model is not None and not _MODEL_ID.match(translate_model.strip()):
        raise ValueError("翻譯模型名稱格式不正確")
    if whisper_model is not None and whisper_model.strip() not in whisper_models():
        raise ValueError("不支援的語音辨識模型")


def _env_path() -> Path:
    p = config.DATA_DIR / ".env"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)
    return p


def _save(name: str, value: str) -> None:
    set_key(str(_env_path()), name, value, quote_mode="never")
    import os

    os.environ[name] = value


def update(api_key: str | None, translate_model: str | None, whisper_model: str | None) -> dict:
    """部分更新：欄位為 None 或空字串（金鑰）表示不變。"""
    validate(api_key, translate_model, whisper_model)
    locked = config.ENV_LOCKED
    # 環境變數優先：被鎖定的項目若要改成不同的值就拒絕（沿用目前值的就略過，前端會一併送出）
    if "ANTHROPIC_API_KEY" in locked and api_key is not None and api_key.strip():
        raise ValueError("API 金鑰由環境變數 ANTHROPIC_API_KEY 指定，無法在介面修改")
    if "TRANSLATE_MODEL" in locked and translate_model is not None and translate_model.strip() != config.TRANSLATE_MODEL:
        raise ValueError("翻譯模型由環境變數 TRANSLATE_MODEL 指定，無法在介面修改")
    if "WHISPER_MODEL" in locked and whisper_model is not None and whisper_model.strip() != config.WHISPER_MODEL:
        raise ValueError("語音辨識模型由環境變數 WHISPER_MODEL 指定，無法在介面修改")

    if api_key is not None and api_key.strip():
        _save("ANTHROPIC_API_KEY", api_key.strip())
    if translate_model is not None and "TRANSLATE_MODEL" not in locked:
        config.TRANSLATE_MODEL = translate_model.strip()
        _save("TRANSLATE_MODEL", config.TRANSLATE_MODEL)
    if whisper_model is not None and "WHISPER_MODEL" not in locked:
        config.WHISPER_MODEL = whisper_model.strip()
        _save("WHISPER_MODEL", config.WHISPER_MODEL)
    return current()


def translate_models() -> dict:
    """向 Anthropic 查詢「這把金鑰實際可用」的模型清單。

    回傳 {"models": [{"id", "name"}], "error": None | "no_key" | "auth" | "failed"}。
    """
    import anthropic

    key = config.current_api_key()
    if not key:
        return {"models": [], "error": "no_key"}
    try:
        client = anthropic.Anthropic(api_key=key, timeout=15, max_retries=1)
        models = [
            {"id": m.id, "name": getattr(m, "display_name", None) or m.id}
            for m in client.models.list(limit=100)
            if m.id.startswith("claude")
        ]
    except anthropic.AuthenticationError:
        return {"models": [], "error": "auth"}
    except Exception:  # noqa: BLE001 — 網路或服務問題：讓前端顯示通用訊息，不洩漏細節
        return {"models": [], "error": "failed"}
    return {"models": models, "error": None}
