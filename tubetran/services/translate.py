"""使用 Claude API 分批翻譯字幕，並確保句數對齊。"""
import json
from pathlib import Path
from typing import Callable

import anthropic

from tubetran import config

SYSTEM_PROMPT = """你是專業的影片字幕翻譯。將輸入字幕翻譯成繁體中文（台灣用語）。
規則：
- 輸入是 JSON 陣列，每個元素為 {"i": 編號, "t": 原文}。每個元素通常是一句完整的話；
  句子太長時會在逗號等處切成兩則，這時每則只翻自己那一部分，接起來要能讀成一句通順的話。
- 標記 "ctx": true 的元素是前後文（可能附上已有的譯文 "tr"），只供理解語意、保持用詞一致，
  不要翻譯、不要輸出。
- 只輸出「需要翻譯」的元素（沒有 "ctx" 的那些），格式為 JSON 陣列，每個元素為 {"i": 編號, "t": 譯文}；
  編號必須一一對應，不可合併、拆分或省略。
- 每個編號的譯文只能包含該編號原文的意思，不可以把其他編號的內容提前或重複翻進來。
- 譯文要自然口語、簡短，適合字幕閱讀；人名、品牌與技術名詞可保留原文，同一個詞前後譯法要一致。
- 訊息開頭若附有「術語表」，表中的詞一律照表上的譯法（包括保留英文的寫法），也參考前後文的 "tr" 沿用既有用詞。
- 每一句都必須有譯文，絕對不可以回傳空字串。
- 不要輸出任何 JSON 以外的文字或 markdown 標記。

範例：
輸入 [{"i":7,"t":"I tried everything.","ctx":true,"tr":"我什麼方法都試過了。"},{"i":8,"t":"We spent the whole weekend trying to fix the bug."},{"i":9,"t":"Turns out it was a missing semicolon."},{"i":10,"t":"Classic.","ctx":true}]
輸出 [{"i":8,"t":"我們花了整個週末想修好那個 bug。"},{"i":9,"t":"結果原因是少了一個分號。"}]"""

MAX_ATTEMPTS = 3
# 每批輸出上限。模型會先思考（實測一批 50 句約 2000～2800 個思考 token，再加上約 1800 個譯文 token），
# 原本 8192 偶爾會被思考吃光、譯文 JSON 被截斷，三次都失敗。
MAX_TOKENS = 16000
FIRST_BATCH = 15  # 第一批的句數（越小越快有可用的譯文）
CTX_BEFORE = 3    # 每批附上前面幾句當前後文（含已有的譯文，讓用詞一致、語意接得上）
CTX_AFTER = 2     # 每批附上後面幾句當前後文（批次最後一句才知道話怎麼接下去）
SKIP_LANGS = {"zh-TW", "zh-Hant", "zh-Hant-TW"}


def _han_script(ch: str) -> str | None:
    """漢字是繁體專用（"T"）還是簡體專用（"S"）；兩邊共用的字回傳 None。
    直接用內建編碼判斷：Big5 只收繁體、GB2312 只收簡體（及少數共用字），只在其中一邊的字就是該字體專用。"""
    def has(codec: str) -> bool:
        try:
            ch.encode(codec)
            return True
        except UnicodeEncodeError:
            return False

    big5, gb = has("big5"), has("gb2312")
    return "T" if big5 and not gb else "S" if gb and not big5 else None


def is_traditional_chinese(text: str) -> bool:
    """文字是不是繁體中文：繁體專用字夠多（至少 5 個），而且遠多於簡體專用字（5 倍以上；容許少數引用、人名）。"""
    t = s = 0
    for ch in text:
        if "一" <= ch <= "鿿":
            kind = _han_script(ch)
            t += kind == "T"
            s += kind == "S"
    return t >= 5 and t >= 5 * s


def resolve_lang(lang: str, segments: list[dict]) -> str:
    """YouTube 常把繁體中文字幕只標成 zh（沒有 -TW、-Hant）。語言是中文時看字幕內容：
    是繁體就改成 zh-Hant，不用翻譯（省時間、省費用）；簡體或看不出來就維持原樣，照常翻成繁體中文。"""
    lang = lang or ""
    if lang.split("-")[0].lower() != "zh" or lang in SKIP_LANGS:
        return lang
    return "zh-Hant" if is_traditional_chinese(" ".join(s["text"] for s in segments)) else lang


def _with_context(segs: list[dict]):
    """回傳 make_payload：把「待翻譯的項目」加上前後文（標記 ctx，附上已有的譯文 tr）。

    每次呼叫都依 segs 的最新內容組出前後文，所以前一批剛翻好的譯文會自動帶進下一批。"""
    before, after = CTX_BEFORE, CTX_AFTER

    def make(pending: list[dict]) -> list[dict]:
        want = {it["i"] for it in pending}
        idx = set(want)
        for i in want:
            idx.update(j for j in range(i - before, i + after + 1) if 0 <= j < len(segs))
        payload = []
        for j in sorted(idx):
            item = {"i": j, "t": segs[j]["text"]}
            if j not in want:
                item["ctx"] = True
                if (segs[j].get("trans") or "").strip():
                    item["tr"] = segs[j]["trans"]
            payload.append(item)
        return payload

    return make


def make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.get_api_key())


def parse_reply(text: str) -> dict[int, str]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("回覆中找不到 JSON 陣列")
    items = json.loads(text[start : end + 1])
    return {int(it["i"]): str(it["t"]) for it in items}


def glossary_text(glossary: dict | None) -> str:
    """術語表放在每批的最前面。方括號拿掉：讀回覆時是找第一個「[」當 JSON 陣列的開頭。"""
    if not glossary:
        return ""
    clean = lambda s: str(s).replace("[", "(").replace("]", ")").strip()  # noqa: E731
    rows = "\n".join(f"- {clean(k)} → {clean(v)}" for k, v in glossary.items())
    return f"術語表（整支影片一律照用這些譯法）：\n{rows}\n\n"


def _translate_batch(
    client,
    items: list[dict],
    title: str,
    system: str = SYSTEM_PROMPT,
    make_payload: Callable[[list[dict]], list[dict]] | None = None,
    glossary: dict | None = None,
) -> dict[int, str]:
    """翻譯一批；缺漏或空白的編號會重試，最多 MAX_ATTEMPTS 次。

    make_payload：把「待翻譯的項目」轉成實際送出的內容（用來附上前後文）。
    glossary：整支影片的術語表 {原文: 譯法}，讓各批的譯法一致。
    """
    make_payload = make_payload or (lambda pending: pending)
    head = glossary_text(glossary)
    result: dict[int, str] = {}
    blank: set[int] = set()  # 模型回傳了空字串的編號
    pending = items
    reason = ""  # 最後一次失敗的原因，全部重試都失敗時附在錯誤訊息裡
    for _ in range(MAX_ATTEMPTS):
        payload = json.dumps(make_payload(pending), ensure_ascii=False)
        resp = client.messages.create(
            model=config.TRANSLATE_MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"{head}影片標題：{title}\n\n{payload}"}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            got = parse_reply(text)
        except (ValueError, KeyError, TypeError) as e:
            reason = failure_reason(resp, text, e)
            continue
        wanted = {it["i"] for it in pending}
        if not wanted <= set(got):
            reason = f"回覆少了 {len(wanted - set(got))} 句"
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
    raise RuntimeError(
        f"翻譯失敗：有 {len(pending)} 句在試了 {MAX_ATTEMPTS} 次後仍未取得譯文"
        + (f"（最後一次：{reason}）" if reason else ""))


def failure_reason(resp, text: str, err: Exception) -> str:
    """說明這次回覆為什麼讀不出譯文，讓使用者看得懂發生了什麼事。"""
    stop = getattr(resp, "stop_reason", "")
    if stop == "max_tokens":
        return f"回覆超過 {MAX_TOKENS} 個 token 的上限被截斷"
    if stop == "refusal":
        return "模型拒絕翻譯這段內容"
    if not text.strip():
        return f"模型沒有回傳文字（stop_reason={stop}）"
    return f"回覆不是正確的 JSON（{type(err).__name__}: {str(err)[:80]}）"


GLOSSARY_PROMPT = """你是專業的影片字幕翻譯，正要把一支影片的字幕翻譯成繁體中文（台灣用語）。
翻譯會分好幾批進行，為了讓整支影片的用詞一致，請先讀完全部字幕，整理一份術語表：
- 收錄反覆出現或容易譯得不一致的詞：技術名詞、專有名詞、人名、品牌、產品、影片自創的概念。
- 為每個詞決定「唯一」的譯法。台灣業界習慣直接使用英文的術語就保留英文（例如 namespace、container image 可視情況保留），
  人名、品牌通常保留原文；一般常用詞不必收錄。
- 同一個詞的不同寫法（大小寫、單複數、空格，例如 C groups / Cgroups / cgroup）列在同一項，統一成一種寫法。
- 最多 40 項。
- 只輸出一個 JSON 物件 {"原文": "譯法", ...}，不要輸出任何其他文字或 markdown 標記。"""

GLOSSARY_MAX = 40
GLOSSARY_INPUT_CHARS = 120_000  # 超長的影片只取前面這麼多字（約 3 萬個 token）來整理術語


def make_glossary(segments: list[dict], lang: str, title: str = "", client=None) -> dict[str, str]:
    """讀完整支影片的原文，整理術語表 {原文: 譯法}。失敗時回傳空的（照常翻譯，只是少了一致性的幫助）。"""
    if lang in SKIP_LANGS or not segments:
        return {}
    text = "\n".join(s["text"] for s in segments)[:GLOSSARY_INPUT_CHARS]
    client = client or make_client()
    try:
        resp = client.messages.create(
            model=config.TRANSLATE_MODEL,
            max_tokens=2048,
            system=GLOSSARY_PROMPT,
            messages=[{"role": "user", "content": f"影片標題：{title}\n\n字幕全文：\n{text}"}],
        )
        reply = "".join(b.text for b in resp.content if b.type == "text")
        start, end = reply.find("{"), reply.rfind("}")
        data = json.loads(reply[start : end + 1]) if 0 <= start < end else {}
    except Exception:  # noqa: BLE001 — 術語表只是輔助，拿不到就照常翻譯
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        k, v = str(k).strip(), str(v).strip()
        if k and v and len(k) <= 60 and len(v) <= 60:
            out[k] = v
    return dict(list(out.items())[:GLOSSARY_MAX])


def repair_missing(
    segments: list[dict], lang: str, title: str = "", client=None, glossary: dict | None = None
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
        items = [{"i": i, "t": out[i]["text"]} for i in missing[b : b + size]]
        for i, tr in _translate_batch(client, items, title, make_payload=_with_context(out), glossary=glossary).items():
            out[i]["trans"] = tr
    return out, len(missing)


def translate_title(title: str, lang: str = "", client=None, glossary: dict | None = None) -> str:
    """翻譯影片標題；原文已是繁體中文時直接回傳。有術語表時照表翻，和字幕用詞一致。"""
    if not title or lang in SKIP_LANGS:
        return title
    client = client or make_client()
    system = "將使用者提供的 YouTube 影片標題翻譯成繁體中文（台灣用語）。人名、品牌與技術名詞可保留原文。只輸出譯文，不要加引號或任何說明。"
    content = title
    if glossary:
        system += "若附有術語表，表中的詞一律照表上的譯法。"
        content = f"{glossary_text(glossary)}標題：{title}"
    resp = client.messages.create(
        model=config.TRANSLATE_MODEL,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": content}],
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
    glossary: dict | None = None,
) -> list[dict]:
    """回傳新的 segments，每句多一個 trans 欄位。

    checkpoint：每批翻完就寫入的暫存檔；失敗後重跑會略過已完成且原文相符的句子。
    glossary：整支影片的術語表（make_glossary），每批都帶上，讓譯法前後一致。
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
    # 每批附上前後幾句當前後文：批次交界處的句子才接得上，前一批的譯法也能沿用
    make_payload = _with_context(out)
    for lo, hi in ranges:
        items = [{"i": i, "t": out[i]["text"]} for i in range(lo, hi) if "trans" not in out[i]]
        if items:
            for i, t in _translate_batch(client, items, title, make_payload=make_payload, glossary=glossary).items():
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
