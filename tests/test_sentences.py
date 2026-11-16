from tubetran.services import sentences

# 回歸資料：dFGPOr_gInY（Docker 影片）8:44–9:11 的自動字幕片段。
# 逐段翻譯時，模型把 "views. When Docker says memory limit," 提前翻進 8:54 那段，之後每段都錯開一格。
DOCKER_FRAGS = [
    {"start": 524.617, "end": 526.377, "text": "Once that clicks, a lot of Docker talk"},
    {"start": 526.377, "end": 528.777, "text": "becomes plain English. When Docker says"},
    {"start": 528.777, "end": 530.977, "text": "port mapping, that is network namespace"},
    {"start": 530.977, "end": 532.897, "text": "stuff meeting the host network. When"},
    {"start": 532.897, "end": 534.497, "text": "Docker says volume mount, that is"},
    {"start": 534.497, "end": 536.377, "text": "carefully sharing a folder across mount"},
    {"start": 536.377, "end": 538.617, "text": "views. When Docker says memory limit,"},
    {"start": 538.617, "end": 540.697, "text": "that is a Cgroup. When a container has"},
    {"start": 540.697, "end": 542.337, "text": "its own host name, that is a UTS"},
    {"start": 542.337, "end": 543.497, "text": "namespace."},
    {"start": 543.497, "end": 545.377, "text": "When root in a container is not real"},
    {"start": 545.377, "end": 547.417, "text": "root on the host, that is user namespace"},
    {"start": 547.417, "end": 549.937, "text": "mapping. See? Same ideas."},
    {"start": 549.937, "end": 551.577, "text": "Friendlier labels."},
]


def test_docker_fragments_become_whole_sentences():
    out = sentences.merge_sentences(DOCKER_FRAGS, "en")
    assert [s["text"] for s in out] == [
        "Once that clicks, a lot of Docker talk becomes plain English.",
        "When Docker says port mapping, that is network namespace stuff meeting the host network.",
        "When Docker says volume mount, that is carefully sharing a folder across mount views.",
        "When Docker says memory limit, that is a Cgroup.",
        "When a container has its own host name, that is a UTS namespace.",
        "When root in a container is not real root on the host, that is user namespace mapping. See?",  # "See?" 太短，併進前一句
        "Same ideas.",
        "Friendlier labels.",
    ]
    # 時間：從頭到尾不倒退、不重疊；第一句從第一段開始，最後一句在最後一段結束
    assert out[0]["start"] == 524.617 and out[-1]["end"] == 551.577
    for a, b in zip(out, out[1:]):
        assert a["start"] < a["end"] <= b["start"]
    # 句子從片段中間開始時，時間依字元位置內插：「When Docker says memory limit」在 "views. " 之後
    memory = out[3]
    assert 536.377 < memory["start"] < 537.0


def test_very_short_sentence_joins_the_previous_one():
    frags = [
        {"start": 0.0, "end": 3.0, "text": "you see every network cable."},
        {"start": 3.0, "end": 3.5, "text": "Chaos."},          # 0.5 秒：單獨顯示會一閃而過
        {"start": 3.5, "end": 6.0, "text": "A namespace helps."},
        {"start": 9.0, "end": 9.6, "text": "Wow."},            # 停頓之後才說：不併
    ]
    out = sentences.merge_sentences(frags, "en")
    assert [s["text"] for s in out] == ["you see every network cable. Chaos.", "A namespace helps.", "Wow."]
    assert out[0]["end"] == 3.5


def test_word_timings_are_used_when_available():
    frags = [
        {"start": 0.0, "end": 3.0, "text": "it works. Then we",
         "words": [[0.0, "it"], [0.4, "works."], [2.5, "Then"], [2.8, "we"]]},
        {"start": 3.0, "end": 4.0, "text": "ship it."},
    ]
    out = sentences.merge_sentences(frags, "en")
    assert [s["text"] for s in out] == ["it works.", "Then we ship it."]
    assert out[1]["start"] == 2.5  # 逐字時間（不是內插出來的位置）
    assert out[0]["end"] == 2.5    # 結束＝下一句開始


def test_long_sentence_is_split_at_a_comma():
    words = "one two three four five six seven eight nine ten".split()
    text = " ".join(words[:5]) + ", " + " ".join(words[5:]) + " " + " ".join(words) + "."
    frags = [{"start": 0.0, "end": 12.0, "text": text}]  # 一句講 12 秒：超過上限
    out = sentences.merge_sentences(frags, "en")
    assert len(out) >= 2
    assert out[0]["text"].endswith("five,")  # 優先在逗號處切
    assert " ".join(s["text"] for s in out) == text  # 內容一個字都沒少


def test_no_punctuation_is_split_by_length_and_pause():
    # 舊式自動字幕沒有標點：靠時間上限與停頓切開
    frags = [{"start": i * 2.0, "end": i * 2.0 + 2.0, "text": f"word{i} more words here"} for i in range(10)]
    out = sentences.merge_sentences(frags, "en")
    assert len(out) > 1 and all(s["end"] - s["start"] <= sentences.MAX_DUR + 2.0 for s in out)
    paused = [{"start": 0.0, "end": 1.0, "text": "hello there"}, {"start": 5.0, "end": 6.0, "text": "general"}]
    assert [s["text"] for s in sentences.merge_sentences(paused, "en")] == ["hello there", "general"]


def test_abbreviations_do_not_end_a_sentence():
    frags = [{"start": 0.0, "end": 3.0, "text": "Dr. Smith met Mr. Jones. Then"}, {"start": 3.0, "end": 4.0, "text": "they left."}]
    assert [s["text"] for s in sentences.merge_sentences(frags, "en")] == ["Dr. Smith met Mr. Jones.", "Then they left."]


def test_cjk_is_joined_without_spaces():
    frags = [{"start": 0.0, "end": 2.0, "text": "今日はいい天気です。明日"}, {"start": 2.0, "end": 3.0, "text": "も晴れるでしょう。"}]
    out = sentences.merge_sentences(frags, "ja")
    assert [s["text"] for s in out] == ["今日はいい天気です。", "明日も晴れるでしょう。"]


def test_to_sentences_keeps_fragments_and_can_be_redone():
    data = {"title": "T", "lang": "en", "via": "auto", "segments": DOCKER_FRAGS}
    once = sentences.to_sentences(data)
    assert once["unit"] == "sentence" and once["fragments"] == DOCKER_FRAGS and len(once["segments"]) == 8
    # 重新處理時從保留的片段重組，結果相同（不會把整句再當成片段處理）
    assert sentences.to_sentences(once)["segments"] == once["segments"]


def test_empty_and_bad_input():
    assert sentences.merge_sentences([], "en") == []
    assert sentences.merge_sentences([{"text": "no times"}], "en") == []
