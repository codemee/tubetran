"""術語表的手動編輯：讀寫、清理規則、用編輯後的術語表重新翻譯、↻ 重新處理時保留。"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from tubetran import config, jobs
from tubetran.main import app

VID = "aaaaaaaaaaa"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    jobs._jobs.clear()
    with TestClient(app) as c:
        yield c


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _make_done(tmp_path, vid=VID, glossary=None):
    """已翻譯完成的影片：translated.json、subs.json（整句）、術語表、標籤、書籤、播放位置。"""
    d = tmp_path / vid
    d.mkdir()
    segs = [{"start": 0.0, "end": 1.0, "text": "Hello cgroup."}]
    glossary = {"cgroup": "cgroup"} if glossary is None else glossary
    d.joinpath("translated.json").write_text(json.dumps(
        {"title": "x", "title_trans": "舊標題", "lang": "en", "via": "manual", "unit": "sentence", "video_id": vid,
         "segments": [{**s, "trans": "舊譯"} for s in segs], "glossary": glossary}), encoding="utf-8")
    d.joinpath("subs.json").write_text(json.dumps(
        {"title": "x", "lang": "en", "via": "manual", "unit": "sentence", "segments": segs}), encoding="utf-8")
    d.joinpath("glossary.json").write_text(json.dumps(glossary), encoding="utf-8")
    d.joinpath("progress.json").write_text(json.dumps({"position": 100, "duration": 600}), encoding="utf-8")
    d.joinpath("tags.json").write_text(json.dumps(["教學"], ensure_ascii=False), encoding="utf-8")
    d.joinpath("bookmarks.json").write_text(json.dumps([{"t": 0.0, "name": "重點"}], ensure_ascii=False), encoding="utf-8")
    return d


def _fake_translate(monkeypatch, seen):
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles",
                        lambda vid: (_ for _ in ()).throw(AssertionError("不應重抓字幕")))
    monkeypatch.setattr(jobs.translate, "translate_segments",
                        lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None:
                        seen.append(glossary) or [{**s, "trans": "新譯"} for s in segments])
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: "新標題")


def test_normalize_glossary():
    out = jobs.normalize_glossary({" C  groups ": " 控制群組 ", "": "x", "a": "", "b": "  "})
    assert out == {"C groups": "控制群組"}
    # 原文忽略大小寫去重：後面的覆蓋前面的
    assert jobs.normalize_glossary([("Docker", "容器"), ("docker", "Docker")]) == {"docker": "Docker"}
    # 長度與數量上限
    long = jobs.normalize_glossary({"k" * 100: "v" * 100})
    assert list(long.items()) == [("k" * jobs.GLOSSARY_KEY_MAX, "v" * jobs.GLOSSARY_VALUE_MAX)]
    many = jobs.normalize_glossary([(f"t{i}", "x") for i in range(100)])
    assert len(many) == jobs.translate.GLOSSARY_MAX
    # 格式不對的輸入不會丟例外
    assert jobs.normalize_glossary(None) == {} and jobs.normalize_glossary([1, ("a",), ("b", "c")]) == {"b": "c"}


def test_get_glossary_returns_terms_and_edited_flag(client, tmp_path):
    _make_done(tmp_path)
    r = client.get(f"/api/library/{VID}/glossary")
    assert r.status_code == 200
    assert r.json() == {"glossary": [{"term": "cgroup", "trans": "cgroup"}], "edited": False}


def test_get_glossary_falls_back_to_result_for_old_cache(client, tmp_path):
    d = _make_done(tmp_path)
    (d / "glossary.json").unlink()
    assert client.get(f"/api/library/{VID}/glossary").json()["glossary"] == [{"term": "cgroup", "trans": "cgroup"}]


def test_get_and_put_glossary_reject_bad_or_missing(client, tmp_path):
    assert client.get("/api/library/short/glossary").status_code == 400
    assert client.get(f"/api/library/{VID}/glossary").status_code == 404
    assert client.put("/api/library/short/glossary", json={"glossary": []}).status_code == 400
    assert client.put(f"/api/library/{VID}/glossary", json={"glossary": []}).status_code == 404
    assert not (tmp_path / VID).exists()  # 不替不存在的影片建資料夾


def test_put_glossary_saves_cleans_and_marks_edited(client, tmp_path):
    d = _make_done(tmp_path)
    r = client.put(f"/api/library/{VID}/glossary", json={"glossary": [
        {"term": " namespace ", "trans": "命名空間"}, {"term": "", "trans": "沒原文"},
        {"term": "Docker", "trans": "容器"}, {"term": "docker", "trans": "Docker"},
    ]})
    assert r.status_code == 200
    assert r.json() == {"glossary": [{"term": "namespace", "trans": "命名空間"}, {"term": "docker", "trans": "Docker"}],
                        "edited": True}
    saved = {"namespace": "命名空間", "docker": "Docker"}
    assert json.loads((d / "glossary.json").read_text(encoding="utf-8")) == saved
    assert jobs.load_result(VID)["glossary"] == saved  # 「檢查」補翻時用的是翻譯結果裡的那份
    assert client.get(f"/api/library/{VID}/glossary").json()["edited"] is True
    assert jobs.load_result(VID)["segments"][0]["trans"] == "舊譯"  # 只存、不重新翻譯


def test_put_glossary_can_empty_the_glossary(client, tmp_path):
    _make_done(tmp_path)
    r = client.put(f"/api/library/{VID}/glossary", json={"glossary": []})
    assert r.json() == {"glossary": [], "edited": True}


def test_retranslate_uses_edited_glossary_and_keeps_captions_and_user_data(client, tmp_path, monkeypatch):
    d = _make_done(tmp_path)
    seen = []
    _fake_translate(monkeypatch, seen)
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不應重新整理")))
    client.put(f"/api/library/{VID}/glossary", json={"glossary": [{"term": "cgroup", "trans": "控制群組"}]})

    r = client.post(f"/api/library/{VID}/retranslate")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert _wait(lambda: jobs.get_job(VID).status == "done"), jobs.get_job(VID).error
    assert seen == [{"cgroup": "控制群組"}]  # 照編輯後的術語表翻
    data = jobs.load_result(VID)
    assert data["segments"][0]["trans"] == "新譯" and data["title_trans"] == "新標題"
    assert data["glossary"] == {"cgroup": "控制群組"}
    assert client.get(f"/api/library/{VID}/glossary").json()["edited"] is True
    assert jobs.load_progress(VID)["position"] == 100 and jobs.load_tags(VID) == ["教學"]
    assert jobs.load_bookmarks(VID) == [{"t": 0.0, "name": "重點"}]
    assert not (d / "trans_partial.json").exists()


def test_retranslate_with_reset_rebuilds_glossary(client, tmp_path, monkeypatch):
    d = _make_done(tmp_path)
    seen = []
    _fake_translate(monkeypatch, seen)
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: {"新": "自動"})
    client.put(f"/api/library/{VID}/glossary", json={"glossary": [{"term": "手動", "trans": "x"}]})

    assert client.post(f"/api/library/{VID}/retranslate", json={"reset_glossary": True}).status_code == 200
    assert _wait(lambda: jobs.get_job(VID).status == "done"), jobs.get_job(VID).error
    assert seen == [{"新": "自動"}]
    assert not (d / "glossary_edited.json").exists()  # 回到「自動整理」
    assert client.get(f"/api/library/{VID}/glossary").json()["edited"] is False


def test_retranslate_refuses_without_key_busy_or_missing(client, tmp_path, monkeypatch):
    d = _make_done(tmp_path)
    with monkeypatch.context() as m:  # 沒有金鑰：不能先把舊翻譯刪掉
        m.setattr(config, "get_api_key", lambda: (_ for _ in ()).throw(RuntimeError("尚未設定 ANTHROPIC_API_KEY")))
        assert client.post(f"/api/library/{VID}/retranslate").status_code == 400
    assert (d / "translated.json").exists()
    jobs._jobs[VID] = jobs.Job(VID)  # 處理中：409
    assert client.post(f"/api/library/{VID}/retranslate").status_code == 409
    assert (d / "translated.json").exists()
    jobs._jobs.clear()
    assert client.post("/api/library/bbbbbbbbbbb/retranslate").status_code == 404
    assert client.post("/api/library/short/retranslate").status_code == 400


def test_reprocess_keeps_edited_glossary_but_replaces_auto_one(client, tmp_path, monkeypatch):
    seen = []
    segs = [{"start": 0.0, "end": 1.0, "text": "line"}]
    monkeypatch.setattr(jobs.subtitles, "fetch_subtitles",
                        lambda vid: {"title": "t", "lang": "en", "source": "manual", "segments": segs, "duration": 1})
    monkeypatch.setattr(jobs.translate, "translate_segments",
                        lambda segments, lang, title="", client=None, on_progress=None, checkpoint=None, glossary=None:
                        seen.append(glossary) or [{**s, "trans": "譯"} for s in segments])
    monkeypatch.setattr(jobs.translate, "translate_title", lambda *a, **k: "標題")
    monkeypatch.setattr(jobs.translate, "make_glossary", lambda *a, **k: {"自動": "整理"})

    # 沒編輯過：↻ 之後重新自動整理
    _make_done(tmp_path)
    assert client.post(f"/api/library/{VID}/reprocess").status_code == 200
    assert _wait(lambda: jobs.get_job(VID).status == "done"), jobs.get_job(VID).error
    assert seen == [{"自動": "整理"}]

    # 手動編輯過：↻ 之後沿用
    client.put(f"/api/library/{VID}/glossary", json={"glossary": [{"term": "手動", "trans": "編輯"}]})
    jobs._jobs.clear()
    assert client.post(f"/api/library/{VID}/reprocess").status_code == 200
    assert _wait(lambda: jobs.get_job(VID).status == "done"), jobs.get_job(VID).error
    assert seen[-1] == {"手動": "編輯"}
    assert client.get(f"/api/library/{VID}/glossary").json()["edited"] is True


def test_export_import_carries_the_edited_flag(client, tmp_path, monkeypatch):
    _make_done(tmp_path)
    client.put(f"/api/library/{VID}/glossary", json={"glossary": [{"term": "手動", "trans": "編輯"}]})
    bundle = jobs.export_bundle([VID])
    assert bundle["videos"][0]["files"]["glossary_edited.json"] == {"edited": True}
    jobs.delete_video(VID)
    assert jobs.import_bundle(bundle)["imported"] == [VID]
    assert client.get(f"/api/library/{VID}/glossary").json() == {
        "glossary": [{"term": "手動", "trans": "編輯"}], "edited": True}

def test_unsaved_glossary_edits_are_flagged_and_confirmed_before_leaving():
    """術語表有未儲存的修改時：鈕上有小圓點、面板狀態文字提示；切換影片、桌面版關閉鈕、重新整理／關閉分頁前都要先確認。"""
    from tubetran import config

    gl = (config.STATIC_DIR / "glossary.js").read_text(encoding="utf-8")
    app = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    desktop = (config.STATIC_DIR / "desktop.js").read_text(encoding="utf-8")
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    assert gl.count("baseline = sig()") == 3                                       # 載入、儲存、重新翻譯／重設後都重設基準
    assert 'btn.dataset.dirty = dirty ? "1" : "0"' in gl and 'baseline = "[]"' in gl  # 標記跟著狀態；換影片時清掉
    assert "window.glossaryConfirmLeave" in gl and 'addEventListener("beforeunload"' in gl
    assert "appConfirm(t(\"confirm_gl_discard\")" in gl and "window.askLeaveThenClose" in gl     # 自製對話框；Alt+F4／工作列關閉由 Python 取消後呼叫它
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="modal"' in html and 'id="modal-ok"' in html and 'id="modal-cancel"' in html
    assert "function appConfirm" in app and 'confirm(t("confirm_gl_discard")' not in gl                                  # 離開確認不再用內建的 confirm（重新翻譯／重設仍是）
    assert "glossaryConfirmLeave" in app.split("async function openUrl")[1][:300]   # 切換影片前確認
    assert "glossaryConfirmLeave" in desktop                                       # 桌面版自製的關閉鈕
    assert '#gl-toggle[data-dirty="1"]::after' in css
    for key in ("gl_dirty", "confirm_gl_discard"):
        assert i18n.count(f"{key}:") == 2                                          # 中英文各一
