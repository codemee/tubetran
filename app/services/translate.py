"""使用 Claude API 分批翻譯字幕，並確保句數對齊。"""
import json
from pathlib import Path
from typing import Callable

import anthropic

from app import config

SYSTEM_PROMPT = """你是專業的影片字幕翻譯。將輸入字幕翻譯成繁體中文（台灣用語）。
規則：
- 輸入是 JSON 陣列，每個元素為 {"i": 編號, "t": 原文}。
- 只輸出 JSON 陣列，每個元素為 {"i": 編號, "t": 譯文}，編號必須與輸入一一對應，不可合併、拆分或省略。
- 譯文要自然口語、簡短，適合字幕閱讀；人名、品牌與技術名詞可保留原文。
- 每一句都必須有譯文，絕對不可以回傳空字串。字幕常把一句話斷成好幾段，如果這句只是片段（例如上一句的後半），
  也請把這個片段單獨翻成通順、能和前後句銜接的中文，不要留空，也不要把它併進其他句。
- 不要輸出任何 JSON 以外的文字或 markdown 標記。"""

# 補翻先前漏掉（空白）的句子；前後文只供理解，不用翻譯
REPAIR_PROMPT = """你是專業的影片字幕翻譯，正在補翻先前漏掉的字幕句子。譯文為繁體中文（台灣用語）。
規則：
- 輸入是 JSON 陣列。沒有 "ctx" 欄位的句子是「需要翻譯」的；標記 "ctx": true 的是前後文，只供理解語意
  （可能附上已有的譯文 "tr"），不要翻譯、不要輸出。
- 需要翻譯的句子常是被斷開的片段（例如上一句的後半），請結合前後文，把該片段單獨翻成通順、能與前後句銜接的中文，
  絕對不可以回傳空字串。
- 只輸出 JSON 陣列，每個元素為 {"i": 編號, "t": 譯文}，編號與需要翻譯的句子一一對應。
- 不要輸出任何 JSON 以外的文字或 markdown 標記。"""

MAX_ATTEMPTS = 3
FIRST_BATCH = 15  # 第一批的句數（越小越快有可用的譯文）
SKIP_LANGS = {"zh-TW", "zh-Hant", "zh-Hant-TW"}


def make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.get_api_key())


def parse_reply(text: str) -> dict[int, str]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("回覆中找不到 JSON 陣列")
    items = json.loads(text[start : end + 1])
    return {int(it["i"]): str(it["t"]) for it in items}


def _translate_batch(
    client,
    items: list[dict],
    title: str,
    system: str = SYSTEM_PROMPT,
    make_payload: Callable[[list[dict]], list[dict]] | None = None,
) -> dict[int, str]:
    """翻譯一批；缺漏或空白的編號會重試，最多 MAX_ATTEMPTS 次。

    make_payload：把「待翻譯的項目」轉成實際送出的內容（補翻時用來附上前後文）。
    """
    make_payload = make_payload or (lambda pending: pending)
    result: dict[int, str] = {}
    blank: set[int] = set()  # 模型回傳了空字串的編號
    pending = items
    for _ in range(MAX_ATTEMPTS):
        payload = json.dumps(make_payload(pending), ensure_ascii=False)
        resp = client.messages.create(
            model=config.TRANSLATE_MODEL,
            max_tokens=8192,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"影片標題：{title}\n\n{payload}"}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            got = parse_reply(text)
        except (ValueError, KeyError, TypeError):
            continue
        wanted = {it["i"] for it in pending}
        for i, tr in got.items():
            if i not in wanted:
                continue
            if tr.strip():
                result[i] = tr.strip()
                blank.discard(i)
            else:  # 空字串視為缺漏，重試
                blank.add(i)
        pending = [it for it in pending if it["i"] not in result]
        if not pending:
            return result
    if all(it["i"] in blank for it in pending):
        # 模型多次都回傳空字串（多半是無法單獨成句的片段或音效）：
        # 退而求其次沿用原文，也不要讓字幕留白，更不要讓整支影片翻譯失敗
        for it in pending:
            result[it["i"]] = it["t"]
        return result
    raise RuntimeError(f"翻譯失敗：有 {len(pending)} 句在重試後仍未取得譯文")


def repair_missing(
    segments: list[dict], lang: str, title: str = "", client=None
) -> tuple[list[dict], int]:
    """替沒有譯文（空白）的句子補翻，並附上前後文幫助銜接。回傳 (新 segments, 補了幾句)。"""
    if lang in SKIP_LANGS:
        return segments, 0
    missing = [i for i, s in enumerate(segments) if not (s.get("trans") or "").strip()]
    if not missing:
        return segments, 0
    client = client or make_client()
    out = [dict(s) for s in segments]
    size = config.BATCH_SIZE
    for b in range(0, len(missing), size):
        chunk = missing[b : b + size]

        def with_context(pending: list[dict]) -> list[dict]:
            want = {it["i"] for it in pending}
            idx = set(want)
            for i in want:  # 每個缺漏的句子，附上前 2 句與後 1 句當前後文
                idx.update(j for j in range(i - 2, i + 2) if 0 <= j < len(out))
            payload = []
            for j in sorted(idx):
                item = {"i": j, "t": out[j]["text"]}
                if j not in want:
                    item["ctx"] = True
                    if (out[j].get("trans") or "").strip():
                        item["tr"] = out[j]["trans"]
                payload.append(item)
            return payload

        items = [{"i": i, "t": out[i]["text"]} for i in chunk]
        for i, tr in _translate_batch(client, items, title, REPAIR_PROMPT, with_context).items():
            out[i]["trans"] = tr
    return out, len(missing)


def translate_title(title: str, lang: str = "", client=None) -> str:
    """翻譯影片標題；原文已是繁體中文時直接回傳。"""
    if not title or lang in SKIP_LANGS:
        return title
    client = client or make_client()
    resp = client.messages.create(
        model=config.TRANSLATE_MODEL,
        max_tokens=300,
        system="將使用者提供的 YouTube 影片標題翻譯成繁體中文（台灣用語）。人名、品牌與技術名詞可保留原文。只輸出譯文，不要加引號或任何說明。",
        messages=[{"role": "user", "content": title}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or title


def translate_segments(
    segments: list[dict],
    lang: str,
    title: str = "",
    client=None,
    on_progress: Callable[[int, int], None] | None = None,
    checkpoint: Path | None = None,
) -> list[dict]:
    """回傳新的 segments，每句多一個 trans 欄位。

    checkpoint：每批翻完就寫入的暫存檔；失敗後重跑會略過已完成且原文相符的句子。
    """
    if lang in SKIP_LANGS:
        return [{**s, "trans": s["text"]} for s in segments]
    client = client or make_client()
    out = [dict(s) for s in segments]
    done = _load_checkpoint(checkpoint)
    for i, s in enumerate(out):
        saved = done.get(str(i))
        if saved and saved[0] == s["text"]:
            s["trans"] = saved[1]
    # 第一批縮小，讓使用者更快就能先用到部分譯文；之後才用完整批次
    size = config.BATCH_SIZE
    ranges, b, step = [], 0, min(size, FIRST_BATCH)
    while b < len(out):
        ranges.append((b, min(b + step, len(out))))
        b, step = b + step, size
    for lo, hi in ranges:
        items = [{"i": i, "t": out[i]["text"]} for i in range(lo, hi) if "trans" not in out[i]]
        if items:
            for i, t in _translate_batch(client, items, title).items():
                out[i]["trans"] = t
            _save_checkpoint(checkpoint, out)
        if on_progress:
            on_progress(hi, len(out))
    return out


def load_checkpoint(path: Path | None) -> dict:
    """讀取檢查點：{"索引": [原文, 譯文]}；檔案不存在或損毀時回傳空 dict。"""
    if path and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


_load_checkpoint = load_checkpoint


def _save_checkpoint(path: Path | None, segs: list[dict]) -> None:
    if path:
        data = {str(i): [s["text"], s["trans"]] for i, s in enumerate(segs) if "trans" in s}
        tmp = path.with_suffix(".tmp")  # 先寫暫存再取代，讀取端不會看到寫一半的檔案
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
