"""可在介面調整的設定：API 金鑰、翻譯模型、語音辨識（STT）模型。

儲存在資料資料夾的 settings.json，同時更新記憶體中的 config，
所以改完立刻對「之後開始的任務」生效，不必重啟。優先順序見 config.py（環境變數 > settings.json > 舊式 .env）。
"""
import json
import os
import re

from tubetran import __version__, config

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
        "version": __version__,  # 顯示在設定面板底部
        "has_key": bool(key),
        "api_key": mask_key(key),
        "translate_model": config.TRANSLATE_MODEL,
        "whisper_model": config.WHISPER_MODEL,
        # 由作業系統環境變數指定的項目：優先於 settings.json，介面只能顯示、不能改
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


def _write_file(values: dict) -> None:
    """整份寫入 settings.json：先寫暫存檔再取代，中途失敗也不會留下寫到一半的設定。
    檔案內含 API 金鑰（明文），所以在支援的系統上限定只有本人可讀寫（0600）。"""
    path = config.DATA_DIR / config.SETTINGS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


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

    # 以記憶體副本為底、再疊上磁碟內容：保留別處手動編輯過的欄位，也不會弄丟尚未寫進檔案的值
    values = {**config.USER_SETTINGS, **config.read_settings_file()}
    if api_key is not None and api_key.strip():
        values["api_key"] = api_key.strip()
    if translate_model is not None and "TRANSLATE_MODEL" not in locked:
        values["translate_model"] = translate_model.strip()
    if whisper_model is not None and "WHISPER_MODEL" not in locked:
        values["whisper_model"] = whisper_model.strip()
    _write_file(values)  # 寫入失敗（OSError）就不更新記憶體，狀態維持一致

    config.USER_SETTINGS.clear()
    config.USER_SETTINGS.update(values)
    if "TRANSLATE_MODEL" not in locked and "translate_model" in values:
        config.TRANSLATE_MODEL = values["translate_model"]
    if "WHISPER_MODEL" not in locked and "whisper_model" in values:
        config.WHISPER_MODEL = values["whisper_model"]
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
