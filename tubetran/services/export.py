"""字幕匯出：SRT / VTT。mode 可為 orig、trans、both。"""


def _text(seg: dict, mode: str) -> str:
    if mode == "orig":
        return seg["text"]
    if mode == "trans":
        return seg.get("trans") or seg["text"]
    if seg.get("trans") == seg["text"]:  # 原文本來就是繁體中文（不需翻譯）：雙語也只寫一次
        return seg["text"]
    return f"{seg['text']}\n{seg.get('trans') or ''}".strip()


def _ts(sec: float, sep: str) -> str:
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def to_srt(segments: list[dict], mode: str = "both") -> str:
    blocks = [
        f"{n}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{_text(s, mode)}\n"
        for n, s in enumerate(segments, 1)
    ]
    return "\n".join(blocks)


def to_vtt(segments: list[dict], mode: str = "both") -> str:
    blocks = [
        f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{_text(s, mode)}\n"
        for s in segments
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)
