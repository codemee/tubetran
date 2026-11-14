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


def test_delete_rejects_bad_id_and_running_job(client, tmp_path):
    assert client.delete("/api/library/..%2Fetc").status_code in (400, 404)
    assert client.delete("/api/library/short").status_code == 400
    _make(tmp_path, "aaaaaaaaaaa", "x", 1000)
    jobs._jobs["aaaaaaaaaaa"] = jobs.Job("aaaaaaaaaaa")  # running
    assert client.delete("/api/library/aaaaaaaaaaa").status_code == 409
    assert (tmp_path / "aaaaaaaaaaa").exists()


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
