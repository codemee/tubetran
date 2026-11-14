"""字幕檢查：修正重複與時序錯亂。純本機規則，不呼叫 API。

處理項目：
- 排除空白（或時間資料壞掉）的句子
- 依開始時間排序（時序錯亂）
- 合併連續重複的句子（自動字幕、Whisper 常見）
- 修正時間：結束早於開始、相鄰句子重疊
- 統計沒有譯文的句子（只回報，不在這裡補翻）
"""
import re

MIN_DUR = 0.3  # 一句字幕至少要有的時間長度（秒）
EPS = 1e-3


def _norm(text: str) -> str:
    """比對重複用：忽略大小寫、空白與標點。"""
    return re.sub(r"[\W_]+", "", text.casefold())


def _default_duration(text: str) -> float:
    """結束時間不合理時，依文字長度估一個閱讀時間（1～6 秒）。"""
    return min(max(len(text) * 0.06, 1.0), 6.0)


def review_segments(segments: list[dict]) -> tuple[list[dict], dict]:
    report = {
        "before": len(segments),
        "after": 0,
        "merged": 0,
        "retimed": 0,
        "reordered": 0,
        "dropped": 0,
        "untranslated": 0,
    }

    # 1. 正規化；排除空白或時間壞掉的句子
    segs: list[dict] = []
    for s in segments:
        text = re.sub(r"\s+", " ", str(s.get("text", ""))).strip()
        try:
            start, end = float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            report["dropped"] += 1
            continue
        if not text:
            report["dropped"] += 1
            continue
        item = {**s, "text": text, "start": start, "end": end}
        if s.get("trans") is not None:
            item["trans"] = str(s["trans"]).strip()
        segs.append(item)

    # 2. 時序錯亂：依開始時間排序（穩定排序，同時間維持原順序）
    report["reordered"] = sum(1 for a, b in zip(segs, segs[1:]) if b["start"] < a["start"])
    if report["reordered"]:
        segs.sort(key=lambda s: s["start"])

    # 3. 合併連續重複。短句（例如「Yeah.」）可能是真的連說兩次，
    #    所以只在時間重疊時才合併；較長的句子允許 1 秒內的間隔。
    merged: list[dict] = []
    for s in segs:
        prev = merged[-1] if merged else None
        n = _norm(s["text"])
        if prev and n and _norm(prev["text"]) == n:
            gap = s["start"] - prev["end"]
            if gap <= (1.0 if len(n) >= 6 else 0.0) + EPS:
                prev["end"] = max(prev["end"], s["end"])
                if not prev.get("trans") and s.get("trans"):
                    prev["trans"] = s["trans"]
                report["merged"] += 1
                continue
        merged.append(s)
    segs = merged

    # 4. 修正時間。原則：只改「結束時間」，起點絕不移動（起點對應語音位置）。
    #    曾經因為把句子往後推而造成連鎖位移，後面的字幕整體飄走，所以不能動起點。
    for i, s in enumerate(segs):
        limit = segs[i + 1]["start"] if i + 1 < len(segs) else None  # 下一句的起點
        # 與下一句重疊：縮短到下一句開始（若會讓這句短於 MIN_DUR，就保持原狀，重疊無害）
        if limit is not None and s["end"] > limit + EPS and limit - s["start"] >= MIN_DUR:
            s["end"] = limit
            report["retimed"] += 1
        # 時間太短或結束早於開始：依文字長度延長，但不超過下一句的起點
        dur = s["end"] - s["start"]
        if dur < MIN_DUR:
            want = s["start"] + _default_duration(s["text"])
            new_end = min(want, limit) if limit is not None else want
            if new_end - s["start"] < MIN_DUR:
                # 沒有足夠空間：原本還有正的時間長度就不動；若是零或負的（句子根本顯示不出來），
                # 才硬給最短時間，寧可輕微重疊
                new_end = s["start"] + MIN_DUR if dur <= EPS else s["end"]
            if abs(new_end - s["end"]) > EPS:
                s["end"] = new_end
                report["retimed"] += 1

    report["after"] = len(segs)
    report["untranslated"] = sum(1 for s in segs if not (s.get("trans") or "").strip())
    return segs, report


def changed(report: dict) -> bool:
    return any(report[k] for k in ("merged", "retimed", "reordered", "dropped"))
