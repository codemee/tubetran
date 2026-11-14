import json
from types import SimpleNamespace

import pytest

from app.services import export, subtitles, translate


def test_parse_video_id():
    assert subtitles.parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1") == "dQw4w9WgXcQ"
    assert subtitles.parse_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert subtitles.parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert subtitles.parse_video_id("https://example.com") is None


def test_parse_json3_dedupes_and_clamps():
    data = {"events": [
        {"tStartMs": 0, "dDurationMs": 3000, "segs": [{"utf8": "Hello\n"}, {"utf8": "world"}]},
        {"tStartMs": 2000, "dDurationMs": 2000, "segs": [{"utf8": "Hello world"}]},
        {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 5000, "dDurationMs": 1000, "segs": [{"utf8": "Next"}]},
        {"tStartMs": 6000},
    ]}
    segs = subtitles.parse_json3(data)
    assert [s["text"] for s in segs] == ["Hello world", "Next"]
    assert segs[0]["end"] == 4.0 and segs[1]["start"] == 5.0


def test_pick_track_uses_video_language_not_first_orig():
    auto = {f"{c}-orig": [c] for c in ("ar", "bn", "en", "fr")}
    # 回歸：曾經誤取第一個 -orig（ar），導致拿阿拉伯文去翻譯
    assert subtitles._pick_track({"language": "en-US", "automatic_captions": auto}) == ("auto", "en", ["en"])
    # 語言不明且有多個候選：不猜，交給 Whisper
    assert subtitles._pick_track({"automatic_captions": auto}) is None
    # 只有一個 -orig 時可直接使用
    assert subtitles._pick_track({"automatic_captions": {"ja-orig": ["ja"]}}) == ("auto", "ja", ["ja"])
    # 人工字幕：en-US 能對應到 en
    assert subtitles._pick_track({"language": "en-US", "subtitles": {"de": [1], "en": [2]}}) == ("manual", "en", [2])


class FakeClient:
    """第一次漏掉最後一句，驗證缺漏重試；並記錄呼叫次數。"""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        content = kw["messages"][0]["content"]
        items = json.loads(content[content.index("["):])
        if self.calls == 1 and len(items) > 1:
            items = items[:-1]
        reply = json.dumps([{"i": it["i"], "t": "譯:" + it["t"]} for it in items], ensure_ascii=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="```json\n" + reply + "\n```")])


def test_translate_batches_and_retries(monkeypatch):
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 3)
    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(5)]
    client = FakeClient()
    out = translate.translate_segments(segs, "en", "t", client=client)
    assert [s["trans"] for s in out] == [f"譯:s{i}" for i in range(5)]
    assert client.calls == 3  # 批次1 兩次（含重試）+ 批次2 一次


def test_translate_resumes_from_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 2)
    cp = tmp_path / "cp.json"
    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(4)]

    class Reliable(FakeClient):
        """完整回覆；fail_after 次呼叫後改為丟錯，模擬 API 中斷。"""

        def __init__(self, fail_after=None):
            super().__init__()
            self.fail_after = fail_after

        def create(self, **kw):
            if self.fail_after is not None and self.calls >= self.fail_after:
                raise RuntimeError("API down")
            self.calls += 1
            content = kw["messages"][0]["content"]
            items = json.loads(content[content.index("["):])
            reply = json.dumps([{"i": it["i"], "t": "譯:" + it["t"]} for it in items], ensure_ascii=False)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    with pytest.raises(RuntimeError):
        translate.translate_segments(segs, "en", client=Reliable(fail_after=1), checkpoint=cp)
    assert json.loads(cp.read_text(encoding="utf-8")).keys() == {"0", "1"}

    client = Reliable()
    out = translate.translate_segments(segs, "en", client=client, checkpoint=cp)
    assert [s["trans"] for s in out] == [f"譯:s{i}" for i in range(4)]
    assert client.calls == 1  # 只翻剩下的第二批

class ScriptedClient:
    """依序回傳預先指定的回覆（字典 {編號: 譯文}），並記錄每次送出的內容。"""

    def __init__(self, *replies):
        self.replies, self.sent, self.messages = list(replies), [], self

    def create(self, **kw):
        content = kw["messages"][0]["content"]
        self.sent.append(json.loads(content[content.index("["):]))
        reply = self.replies.pop(0)
        text = json.dumps([{"i": i, "t": t} for i, t in reply.items()], ensure_ascii=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_blank_translation_is_retried_not_accepted():
    # 第一次：第 1 句回傳空字串 → 視為缺漏，只重送那一句
    client = ScriptedClient({0: "甲", 1: ""}, {1: "乙"})
    out = translate._translate_batch(client, [{"i": 0, "t": "a"}, {"i": 1, "t": "b"}], "t")
    assert out == {0: "甲", 1: "乙"}
    assert [it["i"] for it in client.sent[1]] == [1]


def test_persistent_blank_falls_back_to_original_instead_of_failing():
    client = ScriptedClient({0: "甲", 1: ""}, {1: " "}, {1: ""})
    out = translate._translate_batch(client, [{"i": 0, "t": "a"}, {"i": 1, "t": "of last year."}], "t")
    assert out[0] == "甲" and out[1] == "of last year."  # 不留空白、也不讓整支影片失敗


def test_repair_missing_only_touches_blank_and_sends_context(monkeypatch):
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 50)
    segs = [
        {"start": 0, "end": 1, "text": "I did this", "trans": "我做了這件事"},
        {"start": 1, "end": 2, "text": "like two months", "trans": ""},
        {"start": 2, "end": 3, "text": "of last year.", "trans": None},
        {"start": 3, "end": 4, "text": "Anyway.", "trans": "總之。"},
    ]
    client = ScriptedClient({1: "大約兩個月", 2: "去年的事"})
    out, n = translate.repair_missing(segs, "en", "T", client=client)
    assert n == 2
    assert [s["trans"] for s in out] == ["我做了這件事", "大約兩個月", "去年的事", "總之。"]
    assert segs[1]["trans"] == ""  # 不修改傳入的資料
    sent = {it["i"]: it for it in client.sent[0]}
    assert "ctx" not in sent[1] and "ctx" not in sent[2]  # 缺漏的句子要翻
    assert sent[0]["ctx"] is True and sent[0]["tr"] == "我做了這件事"  # 前後文附上已有的譯文
    assert sent[3]["ctx"] is True


def test_repair_missing_noop_cases():
    done = [{"start": 0, "end": 1, "text": "a", "trans": "甲"}]
    assert translate.repair_missing(done, "en", client=object()) == (done, 0)  # 沒有缺漏：不呼叫 API
    blank_zh = [{"start": 0, "end": 1, "text": "你好", "trans": ""}]
    assert translate.repair_missing(blank_zh, "zh-TW", client=object()) == (blank_zh, 0)


def test_first_batch_is_small(monkeypatch):
    """第一批要小，讓部分譯文盡早可用；之後才用完整批次。"""
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 50)
    monkeypatch.setattr(translate, "FIRST_BATCH", 3)
    sizes, reported = [], []

    class Rec:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            content = kw["messages"][0]["content"]
            items = json.loads(content[content.index("["):])
            sizes.append(len(items))
            reply = json.dumps([{"i": it["i"], "t": "譯"} for it in items], ensure_ascii=False)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(10)]
    translate.translate_segments(segs, "en", client=Rec(), on_progress=lambda d, t: reported.append(d))
    assert sizes == [3, 7] and reported == [3, 10]


def test_translate_title():
    class C:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            assert kw["messages"][0]["content"] == "Hello World"
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=" 哈囉世界 \n")])

    assert translate.translate_title("Hello World", "en", client=C()) == "哈囉世界"
    assert translate.translate_title("你好", "zh-TW", client=object()) == "你好"


def test_translate_skips_traditional_chinese():
    out = translate.translate_segments([{"start": 0, "end": 1, "text": "你好"}], "zh-TW", client=object())
    assert out[0]["trans"] == "你好"


def test_translate_fails_after_retries():
    class Bad(FakeClient):
        def create(self, **kw):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="no json")])

    with pytest.raises(RuntimeError):
        translate.translate_segments([{"start": 0, "end": 1, "text": "a"}], "en", client=Bad())


def test_export_srt_vtt():
    segs = [{"start": 1.5, "end": 3.25, "text": "Hi", "trans": "嗨"}]
    assert "00:00:01,500 --> 00:00:03,250\nHi\n嗨" in export.to_srt(segs)
    assert export.to_vtt(segs, "trans").startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.250\n嗨" in export.to_vtt(segs, "trans")
