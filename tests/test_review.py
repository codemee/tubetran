import json

import pytest
from fastapi.testclient import TestClient

from app import config, jobs
from app.main import app
from app.services import review


def seg(start, end, text, trans="譯"):
    return {"start": start, "end": end, "text": text, "trans": trans}


def test_clean_input_is_untouched():
    segs = [seg(0, 2, "Hello there"), seg(2, 4, "General Kenobi")]
    out, rep = review.review_segments(segs)
    assert out == segs
    assert not review.changed(rep) and rep["before"] == rep["after"] == 2


def test_merges_consecutive_duplicates_keeps_translation():
    segs = [seg(0, 2, "Hello there", ""), seg(1.5, 3, "hello, there!", "你好"), seg(3, 5, "Next line")]
    out, rep = review.review_segments(segs)
    assert [s["text"] for s in out] == ["Hello there", "Next line"]
    assert out[0]["end"] == 3 and out[0]["trans"] == "你好"  # 時間延長、補上有譯文的那份
    assert rep["merged"] == 1 and rep["after"] == 2


def test_short_repeated_lines_only_merge_when_overlapping():
    # 「Yeah.」連說兩次且有間隔：是真的重複說話，不能合併
    out, rep = review.review_segments([seg(0, 1, "Yeah."), seg(1.2, 2, "Yeah.")])
    assert len(out) == 2 and rep["merged"] == 0
    # 時間重疊才視為重複
    out, rep = review.review_segments([seg(0, 1.5, "Yeah."), seg(1, 2, "Yeah.")])
    assert len(out) == 1 and rep["merged"] == 1


def test_far_apart_duplicates_are_kept():
    out, rep = review.review_segments([seg(0, 2, "Thank you very much"), seg(30, 32, "Thank you very much")])
    assert len(out) == 2 and rep["merged"] == 0


def test_reorders_out_of_order_segments():
    out, rep = review.review_segments([seg(5, 7, "second line"), seg(0, 2, "first line"), seg(8, 9, "third line")])
    assert [s["text"] for s in out] == ["first line", "second line", "third line"]
    assert rep["reordered"] == 1


def test_fixes_overlap_and_bad_durations():
    segs = [seg(0, 5, "a long first line"), seg(3, 6, "second line"), seg(10, 10, "zero length"), seg(12, 11, "negative")]
    out, rep = review.review_segments(segs)
    assert out[0]["end"] == 3  # 前一句縮短到下一句開始
    for s in out:
        assert s["end"] - s["start"] >= review.MIN_DUR
    for a, b in zip(out, out[1:]):
        assert a["end"] <= b["start"] + 1e-6
    assert rep["retimed"] >= 3


def test_never_moves_start_times():
    # 兩句幾乎同時開始：不推動任何起點，重疊保持原狀（無害）
    out, rep = review.review_segments([seg(1, 4, "first line here"), seg(1.1, 3, "second line here")])
    assert [s["start"] for s in out] == [1, 1.1] and out[0]["end"] == 4
    assert rep["retimed"] == 0


def test_short_segment_does_not_cascade_into_later_ones():
    """回歸：曾在真實自動字幕上，一句偏短的字幕會被拉長、再把後面所有字幕往後推（位移上百秒）。"""
    segs = [seg(770.72, 770.96, ">> Yeah,")]  # 只比 0.3 秒短一點，且下一句緊接著開始
    t = 770.96
    for i in range(300):
        segs.append(seg(t, t + 1.8, f"line number {i}"))
        t += 1.8
    out, rep = review.review_segments(segs)
    assert [s["start"] for s in out] == [s["start"] for s in segs]  # 所有起點完全不動
    assert [s["end"] for s in out] == [s["end"] for s in segs]  # 空間不夠就維持原狀，不去擠下一句
    assert rep["retimed"] == 0


def test_short_segment_with_room_is_extended_but_not_past_next():
    out, rep = review.review_segments([seg(0, 0.1, "short but roomy line"), seg(10, 12, "later line")])
    assert 0.3 <= out[0]["end"] <= 10 and out[1]["start"] == 10
    assert rep["retimed"] == 1
    out, _ = review.review_segments([seg(0, 0.1, "short"), seg(0.8, 2, "later line")])
    assert out[0]["end"] <= 0.8  # 最多延長到下一句開始


def test_drops_empty_and_broken_and_counts_untranslated():
    segs = [seg(0, 1, "   "), {"text": "no times"}, seg(2, 3, "ok", ""), seg(4, 5, "fine", None)]
    out, rep = review.review_segments(segs)
    assert [s["text"] for s in out] == ["ok", "fine"]
    assert rep["dropped"] == 2 and rep["untranslated"] == 2


# ── 手動檢查端點與流程結束時的自動檢查 ──
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    jobs._jobs.clear()
    with TestClient(app) as c:
        yield c


def _write_result(tmp_path, vid, segments):
    d = tmp_path / vid
    d.mkdir()
    (d / "translated.json").write_text(
        json.dumps({"title": "t", "title_trans": "譯", "lang": "en", "via": "auto", "segments": segments}),
        encoding="utf-8",
    )


def test_check_endpoint_fixes_backs_up_and_reports(client, tmp_path):
    vid = "aaaaaaaaaaa"
    _write_result(tmp_path, vid, [seg(0, 2, "Hello there"), seg(1, 3, "Hello there"), seg(3, 5, "Bye now")])
    res = client.post(f"/api/library/{vid}/check")
    assert res.status_code == 200
    body = res.json()
    assert body["changed"] is True and body["merged"] == 1 and (body["before"], body["after"]) == (3, 2)
    saved = json.loads((tmp_path / vid / "translated.json").read_text(encoding="utf-8"))
    assert len(saved["segments"]) == 2 and saved["review"]["merged"] == 1
    backup = tmp_path / vid / "translated.pre-check.json"
    assert len(json.loads(backup.read_text(encoding="utf-8"))["segments"]) == 3
    # 再檢查一次：已乾淨，不再修改，備份也不被覆蓋
    again = client.post(f"/api/library/{vid}/check").json()
    assert again["changed"] is False
    assert len(json.loads(backup.read_text(encoding="utf-8"))["segments"]) == 3
    assert client.get("/api/library").json()[0]["count"] == 2


def test_check_endpoint_repairs_blank_translations(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    _write_result(tmp_path, vid, [seg(0, 2, "I did this"), seg(2, 4, "of last year.", ""), seg(4, 6, "Anyway")])

    def fake_repair(segs, lang, title="", client=None):
        out = [dict(s) for s in segs]
        out[1]["trans"] = "去年的事"
        return out, 1

    monkeypatch.setattr(jobs.translate, "repair_missing", fake_repair)
    body = client.post(f"/api/library/{vid}/check").json()
    assert body["changed"] is True and body["repaired"] == 1 and body["untranslated"] == 0
    assert "repair_error" not in body
    saved = json.loads((tmp_path / vid / "translated.json").read_text(encoding="utf-8"))
    assert saved["segments"][1]["trans"] == "去年的事"
    assert (tmp_path / vid / "translated.pre-check.json").exists()  # 修改前已備份


def test_check_endpoint_reports_repair_failure_but_keeps_other_fixes(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    _write_result(tmp_path, vid, [seg(0, 2, "Hello there"), seg(1, 3, "Hello there"), seg(3, 5, "Blank", "")])

    def boom(*a, **k):
        raise RuntimeError("API down")

    monkeypatch.setattr(jobs.translate, "repair_missing", boom)
    body = client.post(f"/api/library/{vid}/check").json()
    assert body["merged"] == 1 and body["changed"] is True  # 合併重複仍然生效
    assert "API down" in body["repair_error"] and body["repaired"] == 0 and body["untranslated"] == 1


def test_check_endpoint_errors(client, tmp_path):
    assert client.post("/api/library/aaaaaaaaaaa/check").status_code == 404  # 不存在
    assert client.post("/api/library/short/check").status_code == 400
    d = tmp_path / "bbbbbbbbbbb"
    d.mkdir()
    (d / "subs.json").write_text("{}", encoding="utf-8")  # 只有字幕、尚未翻譯完成
    assert client.post("/api/library/bbbbbbbbbbb/check").status_code == 404


def test_pipeline_auto_reviews_after_translation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    dup = [
        {"start": 0, "end": 2, "text": "Hello there"},
        {"start": 1.5, "end": 3, "text": "Hello there"},
        {"start": 3, "end": 5, "text": "Bye now"},
    ]
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles", lambda vid: {
        "title": "T", "lang": "en", "source": "auto", "segments": dup, "duration": 10})
    monkeypatch.setattr(jobs.translate, "translate_segments",
                        lambda segs, *a, **k: [{**s, "trans": "譯:" + s["text"]} for s in segs])
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: "標題")
    job = jobs.Job("aaaaaaaaaaa")
    jobs._run(job)
    assert job.status == "done", job.error
    data = jobs.load_result("aaaaaaaaaaa")
    assert [s["text"] for s in data["segments"]] == ["Hello there", "Bye now"]
    assert data["review"]["merged"] == 1
