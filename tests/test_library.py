import json

import pytest
from fastapi.testclient import TestClient

from tubetran import config, jobs
from tubetran.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    jobs._jobs.clear()
    with TestClient(app) as c:
        yield c


def _make(tmp_path, vid, title, mtime):
    d = tmp_path / vid
    d.mkdir()
    f = d / "translated.json"
    f.write_text(
        json.dumps({"title": title, "title_trans": "譯:" + title, "lang": "en", "via": "manual", "segments": [{}, {}]}),
        encoding="utf-8",
    )
    (d / "audio.m4a").write_bytes(b"x")
    import os
    os.utime(f, (mtime, mtime))


def test_library_lists_done_videos_newest_first(client, tmp_path):
    _make(tmp_path, "aaaaaaaaaaa", "舊", 1000)
    _make(tmp_path, "bbbbbbbbbbb", "新", 2000)
    (tmp_path / "ccccccccccc").mkdir()  # 沒有 translated.json，不應列出
    res = client.get("/api/library").json()
    assert [i["video_id"] for i in res] == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert res[0]["title"] == "新" and res[0]["count"] == 2


def test_library_backfills_missing_title_trans(client, tmp_path, monkeypatch):
    _make(tmp_path, "aaaaaaaaaaa", "Hello", 1000)
    f = tmp_path / "aaaaaaaaaaa" / "translated.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    del data["title_trans"]  # 模擬舊快取
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(jobs.translate, "translate_title", lambda title, lang="", client=None: "你好")

    assert client.get("/api/library").json()[0]["title_trans"] is None
    for _ in range(50):  # 等背景執行緒寫回
        if "aaaaaaaaaaa" not in jobs._backfilling:
            break
        import time; time.sleep(0.05)
    assert client.get("/api/library").json()[0]["title_trans"] == "你好"


def test_progress_save_resume_and_cleanup(client, tmp_path):
    vid = "aaaaaaaaaaa"
    # 尚未翻譯完成的影片不記錄，也不會替它建立資料夾
    assert client.put(f"/api/progress/{vid}", json={"position": 50, "duration": 600}).json() == {"saved": False}
    assert not (tmp_path / vid).exists()

    _make(tmp_path, vid, "x", 1000)
    assert client.put(f"/api/progress/{vid}", json={"position": 123.4, "duration": 600}).json() == {"saved": True}
    assert jobs.resume_position(jobs.load_progress(vid)) == 123.4
    lib = client.get("/api/library").json()[0]
    assert lib["position"] == 123.4 and lib["duration"] == 600
    assert client.post("/api/process", json={"url": vid}).json()["position"] == 123.4

    # 太接近開頭或結尾：從頭開始
    for pos in (2, 595):
        client.put(f"/api/progress/{vid}", json={"position": pos, "duration": 600})
        assert client.get("/api/library").json()[0]["position"] == 0

    # 輸入驗證
    assert client.put(f"/api/progress/{vid}", json={"position": -1}).status_code == 422
    assert client.put("/api/progress/short", json={"position": 1}).status_code == 400

    # 刪除快取時進度一併清除
    client.put(f"/api/progress/{vid}", json={"position": 100, "duration": 600})
    client.delete(f"/api/library/{vid}")
    assert jobs.load_progress(vid) == {"position": 0.0, "duration": 0.0}


def _make_partial(tmp_path, vid, n_total=4, n_done=2):
    """模擬翻譯進行到一半：有 subs.json 與檢查點，沒有 translated.json。"""
    d = tmp_path / vid
    d.mkdir()
    segs = [{"start": i, "end": i + 1, "text": f"s{i}"} for i in range(n_total)]
    (d / "subs.json").write_text(
        json.dumps({"title": "Partial", "lang": "en", "via": "auto", "segments": segs}), encoding="utf-8"
    )
    cp = {str(i): [f"s{i}", f"譯{i}"] for i in range(n_done)}
    (d / "trans_partial.json").write_text(json.dumps(cp, ensure_ascii=False), encoding="utf-8")


def test_partial_subtitles_are_served_while_translating(client, tmp_path):
    _make_partial(tmp_path, "aaaaaaaaaaa", n_total=4, n_done=2)
    data = client.get("/api/subtitles/aaaaaaaaaaa").json()
    assert data["complete"] is False and data["translated"] == 2
    assert [s.get("trans") for s in data["segments"]] == ["譯0", "譯1", None, None]
    # 下載需等翻譯完成
    assert client.get("/api/subtitles/aaaaaaaaaaa.srt").status_code == 404
    # 原文被改過的檢查點項目不會被誤用
    cp = tmp_path / "aaaaaaaaaaa" / "trans_partial.json"
    cp.write_text(json.dumps({"0": ["別的原文", "錯"]}), encoding="utf-8")
    assert client.get("/api/subtitles/aaaaaaaaaaa").json()["translated"] == 0


def test_complete_subtitles_flag(client, tmp_path):
    _make(tmp_path, "aaaaaaaaaaa", "x", 1000)
    assert client.get("/api/subtitles/aaaaaaaaaaa").json()["complete"] is True


def test_library_lists_running_and_paused_first(client, tmp_path):
    _make(tmp_path, "aaaaaaaaaaa", "Done", 5000)
    _make_partial(tmp_path, "bbbbbbbbbbb", n_total=4, n_done=1)  # 中斷：無執行中的任務
    _make_partial(tmp_path, "ccccccccccc", n_total=4, n_done=2)
    job = jobs.Job("ccccccccccc", stage="translating", progress=0.5)
    jobs._jobs["ccccccccccc"] = job
    (tmp_path / "ddddddddddd").mkdir()  # 只有殘留檔案，不列出
    lib = {i["video_id"]: i for i in client.get("/api/library").json()}
    assert set(lib) == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"}
    assert lib["aaaaaaaaaaa"]["status"] == "done" and lib["aaaaaaaaaaa"]["progress"] == 1.0
    assert lib["bbbbbbbbbbb"]["status"] == "paused" and lib["bbbbbbbbbbb"]["progress"] == 0.25
    assert lib["ccccccccccc"]["status"] == "running" and lib["ccccccccccc"]["progress"] == 0.5
    order = [i["video_id"] for i in client.get("/api/library").json()]
    assert order[-1] == "aaaaaaaaaaa"  # 完成的排在後面


def test_backfill_ignores_unfinished(client, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: called.append(1) or "x")
    _make_partial(tmp_path, "aaaaaaaaaaa")
    client.get("/api/library")
    assert called == []


def test_progress_allowed_for_partial_video(client, tmp_path):
    _make_partial(tmp_path, "aaaaaaaaaaa")
    assert client.put("/api/progress/aaaaaaaaaaa", json={"position": 40, "duration": 600}).json() == {"saved": True}


def test_delete_removes_whole_cache_dir(client, tmp_path):
    _make(tmp_path, "aaaaaaaaaaa", "x", 1000)
    assert client.delete("/api/library/aaaaaaaaaaa").status_code == 200
    assert not (tmp_path / "aaaaaaaaaaa").exists()
    assert client.get("/api/library").json() == []


def test_delete_rejects_bad_id(client):
    assert client.delete("/api/library/..%2Fetc").status_code in (400, 404)
    assert client.delete("/api/library/short").status_code == 400


def test_delete_running_job_requests_cancel_and_keeps_files(client, tmp_path):
    _make(tmp_path, "aaaaaaaaaaa", "x", 1000)
    job = jobs._jobs["aaaaaaaaaaa"] = jobs.Job("aaaaaaaaaaa")  # running（沒有真的執行緒）
    r = client.delete("/api/library/aaaaaaaaaaa")
    assert r.status_code == 202 and r.json() == {"cancelling": "aaaaaaaaaaa"}
    assert job.cancelled and job.stage == "cancelling"
    assert (tmp_path / "aaaaaaaaaaa").exists()  # 檔案由任務結束時自己清，這裡不能動
    # 取消清理完成前不能重新開始同一支影片（會和清理中的任務搶同一個資料夾）
    assert client.post("/api/process", json={"url": "aaaaaaaaaaa"}).status_code == 409


def _fake_pipeline(monkeypatch, translate_fn):
    segs = [{"start": 0.0, "end": 1.0, "text": f"line {i}"} for i in range(3)]
    monkeypatch.setattr(
        jobs.subtitles, "fetch_subtitles",
        lambda vid: {"title": "t", "lang": "en", "source": "manual", "segments": segs, "duration": 3},
    )
    monkeypatch.setattr(jobs.translate, "translate_segments", translate_fn)
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: "標題")
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: {"cgroup": "cgroup"})


def _wait(cond, timeout=5.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_cancel_running_job_cleans_up_cache_and_job(client, tmp_path, monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()

    def slow_translate(segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None):
        started.set()
        release.wait(5)
        on_progress(1, len(segments))  # 每批翻完會呼叫：被取消的話這裡會丟出 Cancelled
        raise AssertionError("取消後不應該繼續翻譯")

    _fake_pipeline(monkeypatch, slow_translate)
    vid = "aaaaaaaaaaa"
    jobs.start_job(vid)
    assert started.wait(5) and (tmp_path / vid / "subs.json").exists()
    assert jobs.delete_video(vid) == "cancelling"
    release.set()
    assert _wait(lambda: vid not in jobs._jobs), "取消後任務應該從清單移除"
    assert not (tmp_path / vid).exists()  # 快取資料夾已清除
    assert not jobs.result_path(vid).exists()


def test_cancel_after_translation_does_not_leave_result(client, tmp_path, monkeypatch):
    import threading

    gate = threading.Event()

    def translate_then_wait(segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None):
        gate.wait(5)  # 翻譯「已經完成」，只差最後寫結果
        return [{**s, "trans": "譯"} for s in segments]

    _fake_pipeline(monkeypatch, translate_then_wait)
    vid = "bbbbbbbbbbb"
    job = jobs.start_job(vid)
    assert _wait(lambda: (tmp_path / vid / "subs.json").exists())
    assert jobs.delete_video(vid) == "cancelling"
    gate.set()
    assert _wait(lambda: vid not in jobs._jobs)
    assert not (tmp_path / vid).exists() and job.status != "done"


def test_delete_after_job_finished_is_a_plain_delete(client, tmp_path, monkeypatch):
    _fake_pipeline(
        monkeypatch,
        lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None:
            [{**s, "trans": "譯"} for s in segments],
    )
    vid = "ccccccccccc"
    jobs.start_job(vid)
    assert _wait(lambda: (jobs.get_job(vid) and jobs.get_job(vid).status == "done"))
    assert client.delete(f"/api/library/{vid}").status_code == 200
    assert not (tmp_path / vid).exists()


def _make_done_with_subs(tmp_path, vid, via):
    """已完成的影片：translated.json、subs.json（舊版逐段格式）、檢查備份、進度與標籤。"""
    _make(tmp_path, vid, "x", 1000)
    d = tmp_path / vid
    frags = [{"start": 0.0, "end": 1.0, "text": "Hello"}, {"start": 1.0, "end": 2.0, "text": "world."}]
    (d / "subs.json").write_text(json.dumps({"title": "x", "lang": "en", "via": via, "segments": frags}), encoding="utf-8")
    (d / "translated.pre-check.json").write_text("{}", encoding="utf-8")
    (d / "progress.json").write_text(json.dumps({"position": 100, "duration": 600}), encoding="utf-8")
    (d / "tags.json").write_text(json.dumps(["教學"], ensure_ascii=False), encoding="utf-8")
    (d / "glossary.json").write_text(json.dumps({"舊": "術語"}, ensure_ascii=False), encoding="utf-8")
    return d


def test_reprocess_refetches_captions_and_keeps_progress_and_tags(client, tmp_path, monkeypatch):
    fetched = []
    _fake_pipeline(monkeypatch, lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None:
                   [{**s, "trans": "譯"} for s in segments])
    real_fetch = jobs.subtitles.fetch_subtitles
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles", lambda vid: fetched.append(vid) or real_fetch(vid))
    vid = "aaaaaaaaaaa"
    d = _make_done_with_subs(tmp_path, vid, "auto")

    r = client.post(f"/api/library/{vid}/reprocess")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert _wait(lambda: jobs.get_job(vid).status == "done"), jobs.get_job(vid).error
    assert fetched == [vid]  # YouTube 字幕：重新抓（能拿到逐字時間）
    data = jobs.load_result(vid)
    assert [s["text"] for s in data["segments"]] == ["line 0 line 1 line 2"]  # 新抓的字幕重組成整句
    assert json.loads((d / "subs.json").read_text(encoding="utf-8"))["unit"] == "sentence"
    assert not (d / "translated.pre-check.json").exists()
    assert data["glossary"] == {"cgroup": "cgroup"}  # 術語表也重新整理（舊的不沿用）
    assert jobs.load_progress(vid)["position"] == 100 and jobs.load_tags(vid) == ["教學"]


def test_glossary_is_made_once_saved_and_reused_on_resume(client, tmp_path, monkeypatch):
    calls, seen = [], []
    _fake_pipeline(monkeypatch, lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None,
                   glossary=None: seen.append(glossary) or [{**s, "trans": "譯"} for s in segments])
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: calls.append(1) or {"cgroup": "cgroup"})
    vid = "aaaaaaaaaaa"
    jobs.start_job(vid)
    assert _wait(lambda: jobs.get_job(vid).status == "done"), jobs.get_job(vid).error
    assert calls == [1] and seen == [{"cgroup": "cgroup"}]  # 整理一次，翻譯時帶上
    assert json.loads((tmp_path / vid / "glossary.json").read_text(encoding="utf-8")) == {"cgroup": "cgroup"}
    assert jobs.load_result(vid)["glossary"] == {"cgroup": "cgroup"}  # 「檢查」補翻時要用
    # 模擬中斷後續翻：術語表沿用存下來的，不再呼叫
    jobs.result_path(vid).unlink()
    jobs._jobs.clear()
    jobs.start_job(vid)
    assert _wait(lambda: jobs.get_job(vid).status == "done")
    assert calls == [1]


def test_reprocess_whisper_keeps_recognition_and_regroups(client, tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch, lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None:
                   [{**s, "trans": "譯"} for s in segments])
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles", lambda vid: (_ for _ in ()).throw(AssertionError("不應重抓")))
    monkeypatch.setattr(jobs.transcribe, "download_audio", lambda *a: (_ for _ in ()).throw(AssertionError("不應重新辨識")))
    vid = "bbbbbbbbbbb"
    _make_done_with_subs(tmp_path, vid, "whisper")

    assert client.post(f"/api/library/{vid}/reprocess").status_code == 200
    assert _wait(lambda: jobs.get_job(vid).status == "done"), jobs.get_job(vid).error
    assert [s["text"] for s in jobs.load_result(vid)["segments"]] == ["Hello world."]


def test_reprocess_refuses_without_key_busy_or_missing(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    d = _make_done_with_subs(tmp_path, vid, "auto")
    # 沒有金鑰：不能先把舊翻譯刪掉
    with monkeypatch.context() as m:
        m.setattr(config, "get_api_key", lambda: (_ for _ in ()).throw(RuntimeError("尚未設定 ANTHROPIC_API_KEY")))
        assert client.post(f"/api/library/{vid}/reprocess").status_code == 400
    assert (d / "translated.json").exists() and (d / "subs.json").exists()
    # 處理中：409，檔案不動
    jobs._jobs[vid] = jobs.Job(vid)
    assert client.post(f"/api/library/{vid}/reprocess").status_code == 409
    assert (d / "translated.json").exists()
    jobs._jobs.clear()
    # 找不到影片、ID 不合法
    assert client.post("/api/library/ccccccccccc/reprocess").status_code == 404
    assert client.post("/api/library/short/reprocess").status_code == 400


def test_normalize_tags():
    assert jobs.normalize_tags([" Python ", "python", "", "  ", "AI  工具", "x" * 50]) == ["Python", "AI 工具", "x" * jobs.MAX_TAG_LEN]
    assert len(jobs.normalize_tags([str(i) for i in range(30)])) == jobs.MAX_TAGS


def test_tags_save_list_and_cleanup(client, tmp_path):
    vid = "aaaaaaaaaaa"
    # 沒有快取的影片：404，且不會替它建立資料夾
    assert client.put(f"/api/library/{vid}/tags", json={"tags": ["a"]}).status_code == 404
    assert not (tmp_path / vid).exists()
    assert client.put("/api/library/bad!/tags", json={"tags": ["a"]}).status_code in (400, 404)

    _make(tmp_path, vid, "x", 1000)
    assert client.get("/api/library").json()[0]["tags"] == []
    res = client.put(f"/api/library/{vid}/tags", json={"tags": [" 教學 ", "教學", "Python"]})
    assert res.json() == {"tags": ["教學", "Python"]}
    assert client.get("/api/library").json()[0]["tags"] == ["教學", "Python"]

    # 清空標籤
    assert client.put(f"/api/library/{vid}/tags", json={"tags": []}).json() == {"tags": []}
    assert client.get("/api/library").json()[0]["tags"] == []

    # 刪除影片時標籤一起清除
    client.put(f"/api/library/{vid}/tags", json={"tags": ["a"]})
    assert client.delete(f"/api/library/{vid}").status_code == 200
    assert not (tmp_path / vid).exists()


def test_tags_file_corrupt_is_ignored(client, tmp_path):
    vid = "aaaaaaaaaaa"
    _make(tmp_path, vid, "x", 1000)
    (tmp_path / vid / "tags.json").write_text("{not json", encoding="utf-8")
    assert client.get("/api/library").json()[0]["tags"] == []
