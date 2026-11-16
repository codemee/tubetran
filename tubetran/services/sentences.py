"""把字幕片段重組成「一句一則」，再拿去翻譯。

為什麼：自動字幕依說話節奏斷行，常斷在片語中間（例如 "across mount" / "views."）。逐段翻譯時，模型會把
整句翻完塞進前一段，之後每一段都錯開一格（連鎖錯位）。改成整句翻譯，就不需要把中文切回英文的斷點。

做法：
1. 把每個片段拆成「字」，每個字帶時間：json3 自動字幕有逐字時間（words）；沒有的就依字元位置在片段內內插。
2. 依句尾標點（. ? ! 。 ？ ！ …）分句。
3. 太長的句子（時間或字數超過上限）在逗號等處切開；沒有標點可切時在字的邊界切。
4. 片段之間停頓太久也視為斷句（沒有標點的舊式自動字幕靠這個與上限來切）。
5. 時間：開始＝第一個字的時間；結束＝下一句開始（或最後一個字所在片段的結束，取較早者）。
6. 不到 1 秒的短句（"Chaos."）併進前一句，避免一閃而過。
"""
import re

SENT_END = re.compile(r"[.!?。！？…]+[\"'”’」』)\]）]*$")
SOFT_END = re.compile(r"[,;:，；：、—–]+[\"'”’」』)\]）]*$")
# 句點不代表句尾的縮寫（只列常見、幾乎不會出現在句尾的）
ABBREV = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "e.g.", "i.e."}
# 不以空白分詞的語言：片段接起來時不加空白，長度上限也較短
NO_SPACE_LANGS = {"zh", "ja", "th", "lo", "km", "my"}

MAX_DUR = 8.0         # 一則最長秒數（超過就切）
MAX_CHARS = 110       # 以空白分詞的語言：一則最多字元數
MAX_CHARS_NOSPACE = 40
PAUSE = 1.5           # 片段之間停頓超過這個秒數：視為斷句
MIN_DUR = 0.3
MIN_SHOW = 1.0        # 短於這個秒數的句子，盡量併進前一句

_WORD = re.compile(r"\S+")
_NOSPACE_PIECE = re.compile(r"[^。！？!?…]*[。！？!?…]+[」』）)\"”’]*|[^。！？!?…]+")


def is_no_space(lang: str) -> bool:
    return (lang or "").split("-")[0].lower() in NO_SPACE_LANGS


def _split(text: str, nospace: bool) -> list[tuple[int, str]]:
    """切成 (字元位置, 字)；不分詞的語言以句尾標點為界切成幾段。"""
    pat = _NOSPACE_PIECE if nospace else _WORD
    return [(m.start(), m.group().strip()) for m in pat.finditer(text) if m.group().strip()]


def _tokens(frags: list[dict], nospace: bool) -> list[tuple[float, str, float]]:
    """所有片段的字：(時間, 字, 所在片段的結束時間)，時間保證不倒退。"""
    toks: list[tuple[float, str, float]] = []
    last = float("-inf")
    for f in frags:
        try:
            start, end = float(f["start"]), float(f["end"])
        except (KeyError, TypeError, ValueError):
            continue
        end = max(end, start)
        items: list[tuple[float, str]] = []
        words = f.get("words")
        if words:
            for t, chunk in words:
                for _, w in _split(str(chunk), nospace):
                    items.append((float(t), w))
        else:
            text = str(f.get("text", ""))
            n = max(len(text), 1)
            items = [(start + (end - start) * pos / n, w) for pos, w in _split(text, nospace)]
        for t, w in items:
            t = max(min(max(t, start), end), last)
            last = t
            toks.append((t, w, end))
    return toks


def _is_sentence_end(word: str) -> bool:
    return bool(SENT_END.search(word)) and word.casefold() not in ABBREV


def merge_sentences(frags: list[dict], lang: str = "") -> list[dict]:
    """片段 [{start, end, text, words?}] → 整句 [{start, end, text}]。"""
    nospace = is_no_space(lang)
    sep = "" if nospace else " "
    max_chars = MAX_CHARS_NOSPACE if nospace else MAX_CHARS
    toks = _tokens(frags, nospace)

    def text_of(g):
        return sep.join(w for _, w, _ in g)

    groups: list[list] = []
    cur: list = []
    for tok in toks:
        if cur and tok[0] - cur[-1][2] > PAUSE:  # 和上一個字所在片段之間停頓很久
            groups.append(cur)
            cur = []
        if cur and (tok[0] - cur[0][0] > MAX_DUR or len(text_of(cur + [tok])) > max_chars):
            # 太長：優先在逗號等處切（切點不要太靠前，否則前一則太短），沒有就在這個字之前切
            cut = next((j for j in range(len(cur) - 1, 0, -1)
                        if SOFT_END.search(cur[j][1]) and j + 1 >= len(cur) * 0.3), None)
            if cut is None:
                groups.append(cur)
                cur = []
            else:
                groups.append(cur[: cut + 1])
                cur = cur[cut + 1:]
        cur.append(tok)
        if _is_sentence_end(tok[1]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    out: list[dict] = []
    for k, g in enumerate(groups):
        start = g[0][0]
        end = g[-1][2]
        if k + 1 < len(groups):
            end = min(end, groups[k + 1][0][0])
        text = text_of(g)
        prev = out[-1] if out else None
        # 很短的句子（"Chaos."、"No fight."）單獨顯示會一閃而過：和前一句連著講、合併後也不太長，就併進前一句
        if (prev and end - start < MIN_SHOW and start - prev["end"] < 0.05
                and end - prev["start"] <= MAX_DUR and len(prev["text"] + sep + text) <= max_chars):
            prev["end"] = round(end, 3)
            prev["text"] += sep + text
            continue
        if end - start < MIN_DUR:  # 太短：延長一點（之後的自動檢查會再處理與下一句的重疊）
            end = start + MIN_DUR
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return out


def to_sentences(data: dict) -> dict:
    """把 subs.json 的資料轉成整句版本：原本的片段保留在 fragments（重新處理時用），segments 改成整句。"""
    frags = data.get("fragments") or data.get("segments") or []
    return {
        **data,
        "fragments": frags,
        "segments": merge_sentences(frags, data.get("lang", "")),
        "unit": "sentence",
    }
