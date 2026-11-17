import json
from types import SimpleNamespace

import pytest

from tubetran.services import export, subtitles, translate


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


def test_parse_json3_keeps_word_timings():
    data = {"events": [
        {"tStartMs": 1000, "dDurationMs": 3000, "segs": [
            {"utf8": "carefully"}, {"utf8": " sharing", "tOffsetMs": 400}, {"utf8": " a folder", "tOffsetMs": 900}]},
        {"tStartMs": 3500, "dDurationMs": 2000, "segs": [{"utf8": "views."}]},  # 只有一段：不記 words
    ]}
    segs = subtitles.parse_json3(data)
    assert segs[0]["words"] == [[1.0, "carefully"], [1.4, "sharing"], [1.9, "a folder"]]
    assert segs[0]["end"] == 3.5  # 與下一段重疊：截到下一段開始
    assert "words" not in segs[1]


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


def test_pick_track_ignores_manual_track_in_other_language():
    # 回歸：英文影片只有別人上傳的俄文人工字幕，曾誤取俄文去翻譯；應改用英文自動字幕原始軌
    info = {
        "language": "en-US",
        "subtitles": {"ru": ["ru-fmt"]},
        "automatic_captions": {"en-orig": ["en-fmt"], "ru": ["x"]},
    }
    assert subtitles._pick_track(info) == ("auto", "en", ["en-fmt"])
    # 同語系的變體（en-GB）仍視為相符
    assert subtitles._pick_track({"language": "en-US", "subtitles": {"en-GB": [1], "ru": [2]}}) == ("manual", "en-GB", [1])
    # 只有他語人工字幕、也沒有自動字幕：不採用，交給 Whisper
    assert subtitles._pick_track({"language": "en-US", "subtitles": {"ru": [1]}}) is None
    # 影片語言不明、只有一軌人工字幕：沒有更好的選擇，照用
    assert subtitles._pick_track({"subtitles": {"ja": [1]}}) == ("manual", "ja", [1])


def _todo(kw) -> list[dict]:
    """送出的內容中「需要翻譯」的項目（不含標記 ctx 的前後文）；真正的模型也只會回這些。"""
    content = kw["messages"][0]["content"]
    return [it for it in json.loads(content[content.index("["):]) if not it.get("ctx")]


class FakeClient:
    """第一次漏掉最後一句，驗證缺漏重試；並記錄呼叫次數。"""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        items = _todo(kw)
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
            reply = json.dumps([{"i": it["i"], "t": "譯:" + it["t"]} for it in _todo(kw)], ensure_ascii=False)
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
            items = _todo(kw)
            sizes.append(len(items))
            reply = json.dumps([{"i": it["i"], "t": "譯"} for it in items], ensure_ascii=False)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(10)]
    translate.translate_segments(segs, "en", client=Rec(), on_progress=lambda d, t: reported.append(d))
    assert sizes == [3, 7] and reported == [3, 10]


def test_each_batch_gets_context_from_neighbours(monkeypatch):
    """回歸：批次交界的句子看不到上下文（"...before we" / "wrap up."），翻出來接不上。
    每批要附上前一批最後幾句（含譯文）與下一批開頭幾句，標記 ctx。"""
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 4)
    monkeypatch.setattr(translate, "FIRST_BATCH", 4)
    monkeypatch.setattr(translate, "CTX_BEFORE", 2)
    monkeypatch.setattr(translate, "CTX_AFTER", 1)
    sent = []

    class Rec:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            content = kw["messages"][0]["content"]
            sent.append(json.loads(content[content.index("["):]))
            reply = json.dumps([{"i": it["i"], "t": "譯" + it["t"]} for it in _todo(kw)], ensure_ascii=False)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(8)]
    out = translate.translate_segments(segs, "en", client=Rec())
    assert [s["trans"] for s in out] == [f"譯s{i}" for i in range(8)]
    # 第一批：0–3 要翻，後面附 4 當前後文（還沒有譯文）
    assert [(it["i"], it.get("ctx", False), it.get("tr")) for it in sent[0]] == [
        (0, False, None), (1, False, None), (2, False, None), (3, False, None), (4, True, None)]
    # 第二批：前面附 2、3（帶著剛翻好的譯文），4–7 要翻
    assert [(it["i"], it.get("ctx", False), it.get("tr")) for it in sent[1]] == [
        (2, True, "譯s2"), (3, True, "譯s3"), (4, False, None), (5, False, None), (6, False, None), (7, False, None)]


class Replying:
    """固定回覆一段文字，並記錄送出的參數。"""

    def __init__(self, text):
        self.text, self.kw, self.messages = text, None, self

    def create(self, **kw):
        self.kw = kw
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_make_glossary_reads_whole_transcript_and_cleans_reply():
    segs = [{"text": "Namespaces hide."}, {"text": "C groups limit."}]
    c = Replying('術語表如下：\n{"namespace": "namespace", "C groups / cgroup": "cgroups", "": "空", "x": ""}')
    g = translate.make_glossary(segs, "en", "Docker", client=c)
    assert g == {"namespace": "namespace", "C groups / cgroup": "cgroups"}  # 空的項目丟掉
    sent = c.kw["messages"][0]["content"]
    assert "Namespaces hide.\nC groups limit." in sent and "Docker" in sent  # 全文都送去整理


def test_make_glossary_failures_are_harmless():
    segs = [{"text": "a"}]
    assert translate.make_glossary(segs, "en", client=Replying("抱歉，我無法")) == {}
    assert translate.make_glossary(segs, "en", client=Replying('["not", "a dict"]')) == {}

    class Down:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("API down")

    assert translate.make_glossary(segs, "en", client=Down()) == {}  # 拿不到術語表也照常翻譯
    assert translate.make_glossary(segs, "zh-TW", client=object()) == {}  # 不需要翻譯的語言：不呼叫 API


def test_glossary_is_sent_with_every_batch(monkeypatch):
    monkeypatch.setattr(translate.config, "BATCH_SIZE", 2)
    monkeypatch.setattr(translate, "FIRST_BATCH", 2)
    contents = []

    class Rec:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            contents.append(kw["messages"][0]["content"])
            reply = json.dumps([{"i": it["i"], "t": "譯"} for it in _todo(kw)], ensure_ascii=False)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])

    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(4)]
    glossary = {"namespace": "namespace", "odd [x]": "怪"}
    translate.translate_segments(segs, "en", client=Rec(), glossary=glossary)
    assert len(contents) == 2
    for c in contents:
        assert c.startswith("術語表") and "- namespace → namespace" in c
        assert "odd (x)" in c and c.index("[") > c.index("影片標題")  # 方括號換掉：回覆解析靠第一個「[」


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
    # 有術語表時，標題也照表翻，和字幕用詞一致
    c = Replying("Docker 容器如何運作：namespace 與 cgroups")
    translate.translate_title("How Docker Works: Namespaces & cgroups", "en", client=c, glossary={"namespace": "namespace"})
    assert "- namespace → namespace" in c.kw["messages"][0]["content"] and "術語表" in c.kw["system"]


def test_translate_skips_traditional_chinese():
    out = translate.translate_segments([{"start": 0, "end": 1, "text": "你好"}], "zh-TW", client=object())
    assert out[0]["trans"] == "你好"


def test_translate_fails_after_retries():
    class Bad(FakeClient):
        def create(self, **kw):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="no json")])

    with pytest.raises(RuntimeError) as e:
        translate.translate_segments([{"start": 0, "end": 1, "text": "a"}], "en", client=Bad())
    assert "最後一次：回覆不是正確的 JSON" in str(e.value)  # 告訴使用者實際發生了什麼


def test_translate_failure_explains_truncated_reply():
    """回覆被輸出上限截斷（模型思考吃掉太多 token）：錯誤訊息要講出來，不能只說「重試後仍未取得譯文」。"""
    seen = []

    class Cut(FakeClient):
        def create(self, **kw):
            seen.append(kw["max_tokens"])
            return SimpleNamespace(stop_reason="max_tokens", content=[SimpleNamespace(type="text", text='[{"i":0,"t":"半')])

    with pytest.raises(RuntimeError) as e:
        translate.translate_segments([{"start": 0, "end": 1, "text": "a"}], "en", client=Cut())
    assert "token 的上限被截斷" in str(e.value) and f"試了 {translate.MAX_ATTEMPTS} 次" in str(e.value)
    assert seen and all(n >= 16000 for n in seen)  # 上限要留給思考＋50 句譯文（原本 8192 不夠）


def test_translate_failure_explains_missing_lines():
    class Short(FakeClient):
        def create(self, **kw):
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text='[{"i":0,"t":"甲"}]')])

    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(3)]
    with pytest.raises(RuntimeError) as e:
        translate.translate_segments(segs, "en", client=Short())
    assert "有 2 句" in str(e.value) and "回覆少了 2 句" in str(e.value)


def test_export_srt_vtt():
    segs = [{"start": 1.5, "end": 3.25, "text": "Hi", "trans": "嗨"}]
    assert "00:00:01,500 --> 00:00:03,250\nHi\n嗨" in export.to_srt(segs)
    assert export.to_vtt(segs, "trans").startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.250\n嗨" in export.to_vtt(segs, "trans")
