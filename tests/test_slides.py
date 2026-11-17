"""投影片的畫面：下載影片（1080p 優先）、在每則字幕的時間點擷取 JPEG、背景任務與 API。"""
import json
import time

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tubetran import config, jobs
from tubetran.main import app
from tubetran.services import frames

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]  # 第 0、1、2 秒的畫面顏色


def make_video(path, seconds=3, fps=10, size=(64, 48)):
    """產生一支每秒換一種顏色的小影片（不需要網路）。"""
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=fps)
        s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        for i in range(seconds * fps):
            rgb = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            rgb[:, :] = COLORS[(i // fps) % len(COLORS)]
            for p in s.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return path


def jpeg_color(path):
    with av.open(str(path)) as c:
        f = next(c.decode(video=0))
    return tuple(int(v) for v in f.to_ndarray(format="rgb24").reshape(-1, 3).mean(axis=0))


def close(a, b, tol=40):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_extracts_one_jpeg_per_time_point_at_the_right_moment(tmp_path):
    video = make_video(tmp_path / "video.mp4")
    out = tmp_path / "slides"
    seen = []
    n = frames.extract_frames(video, [0.05, 1.05, 2.05, 1.5, 99.0], out, seen.append)
    assert n == 5 and seen == [1, 2, 3, 4, 5]                          # 每張都回報（網頁可以先用已經好的）
    assert sorted(p.name for p in out.iterdir()) == ["0000.jpg", "0001.jpg", "0002.jpg", "0003.jpg", "0004.jpg"]
    assert (out / "0000.jpg").read_bytes()[:2] == b"\xff\xd8"          # JPEG
    assert close(jpeg_color(out / "0000.jpg"), COLORS[0])
    assert close(jpeg_color(out / "0001.jpg"), COLORS[1])
    assert close(jpeg_color(out / "0002.jpg"), COLORS[2])
    assert close(jpeg_color(out / "0003.jpg"), COLORS[1])               # 時間往回：要重新跳轉
    assert close(jpeg_color(out / "0004.jpg"), COLORS[2])               # 超過影片長度：用最後一格


def test_extraction_can_be_cancelled(tmp_path):
    class Stop(Exception):
        pass

    video = make_video(tmp_path / "video.mp4")
    calls = []

    def check():
        calls.append(1)
        if len(calls) > 1:
            raise Stop

    with pytest.raises(Stop):
        frames.extract_frames(video, [0.05, 1.05, 2.05], tmp_path / "s", check=check)
    assert [p.name for p in (tmp_path / "s").iterdir()] == ["0000.jpg"]


def test_frame_time_is_just_before_the_subtitle_ends():
    """回歸：擷取字幕「開始」那一格，常剛好是影片轉場（淡入），畫面像蒙了一層。改成結束前一點點。"""
    assert frames.frame_time({"start": 10.0, "end": 13.0}) == 12.75   # 結束前 0.25 秒
    assert frames.frame_time({"start": 10.0, "end": 10.3}) == 10.15   # 很短的句子：不早於中間
    seg = {"start": 10.0, "end": 13.0}
    assert seg["start"] < frames.frame_time(seg) < seg["end"]          # 仍在這則字幕的時間內


def test_prefers_1080p_h264_over_https():
    f = frames.VIDEO_FORMAT
    assert f.startswith("bestvideo[height<=1080][vcodec^=avc1][protocol^=http]")
    assert "bestvideo[height<=1080]" in f and f.endswith("/best")    # 沒有 1080p 才退到較低畫質


# ── 背景任務與 API ──
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    jobs._jobs.clear()
    jobs._slide_jobs.clear()
    with TestClient(app) as c:
        yield c


def _done_video(tmp_path, vid="aaaaaaaaaaa", starts=(0.0, 1.0, 2.0)):
    d = tmp_path / vid
    d.mkdir(exist_ok=True)
    segs = [{"start": s, "end": s + 1.0, "text": f"s{s}", "trans": "譯"} for s in starts]
    (d / "translated.json").write_text(json.dumps({"title": "T", "segments": segs}), encoding="utf-8")
    return d


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_slides_are_prepared_on_demand_and_the_video_is_deleted(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    d = _done_video(tmp_path)
    downloads = []

    def fake_download(video_id, out_dir, check=None, on_progress=None):
        downloads.append(video_id)
        on_progress(1.0)
        return make_video(out_dir / "video.mp4")

    monkeypatch.setattr(jobs.frames, "download_video", fake_download)
    assert client.get(f"/api/slides/{vid}").json()["status"] == "none"   # 還沒準備：不會自己開始
    assert downloads == []
    r = client.post(f"/api/slides/{vid}").json()
    assert r["status"] == "running" and r["total"] == 3
    assert _wait(lambda: client.get(f"/api/slides/{vid}").json()["status"] == "done")
    st = client.get(f"/api/slides/{vid}").json()
    assert st["ready"] == 3 and st["stamp"] > 0
    img = client.get(f"/api/slides/{vid}/1.jpg")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert not list((d / "slides").glob("video.*"))                     # 擷取完就刪掉影片
    # 已經好了：再進入投影片模式不會重新下載
    assert client.post(f"/api/slides/{vid}").json()["status"] == "done" and downloads == [vid]
    assert client.get(f"/api/slides/{vid}/9.jpg").status_code == 404


def test_slides_are_redone_when_the_sentences_change(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    d = _done_video(tmp_path)
    (d / "slides").mkdir()
    times = [frames.frame_time({"start": s, "end": s + 1.0}) for s in (0.0, 1.0, 2.0)]
    (d / "slides" / "slides.json").write_text(json.dumps({"times": times, "stamp": 1}), encoding="utf-8")
    assert client.get(f"/api/slides/{vid}").json()["status"] == "done"
    _done_video(tmp_path, starts=(0.0, 1.5))                             # 重新處理後句子變了
    assert client.get(f"/api/slides/{vid}").json()["status"] == "none"


def test_slides_need_finished_subtitles_and_a_valid_id(client):
    assert client.get("/api/slides/aaaaaaaaaaa").status_code == 404
    assert client.post("/api/slides/aaaaaaaaaaa").status_code == 404
    assert client.get("/api/slides/short").status_code == 400
    assert client.get("/api/slides/aaaaaaaaaaa/-1.jpg").status_code == 404


def test_download_failure_is_reported_and_can_be_retried(client, tmp_path, monkeypatch):
    vid = "aaaaaaaaaaa"
    _done_video(tmp_path)

    def broken(*a, **k):
        raise RuntimeError("影片下載失敗")

    monkeypatch.setattr(jobs.frames, "download_video", broken)
    client.post(f"/api/slides/{vid}")
    assert _wait(lambda: client.get(f"/api/slides/{vid}").json()["status"] == "error")
    assert "影片下載失敗" in client.get(f"/api/slides/{vid}").json()["error"]
    monkeypatch.setattr(jobs.frames, "download_video",
                        lambda video_id, out_dir, check=None, on_progress=None: make_video(out_dir / "video.mp4"))
    assert client.post(f"/api/slides/{vid}").json()["status"] == "running"  # 重新進入投影片模式就再試一次
    assert _wait(lambda: client.get(f"/api/slides/{vid}").json()["status"] == "done")


def test_deleting_the_video_cancels_slide_preparation(client, tmp_path, monkeypatch):
    import threading

    vid = "aaaaaaaaaaa"
    _done_video(tmp_path)
    started, release = threading.Event(), threading.Event()

    def slow_download(video_id, out_dir, check=None, on_progress=None):
        started.set()
        release.wait(5)
        check()  # 被取消就在這裡停下來
        return make_video(out_dir / "video.mp4")

    monkeypatch.setattr(jobs.frames, "download_video", slow_download)
    client.post(f"/api/slides/{vid}")
    assert started.wait(5)
    assert client.delete(f"/api/library/{vid}").status_code == 200
    release.set()
    assert _wait(lambda: not (tmp_path / vid).exists() or not (tmp_path / vid / "slides").exists())
    time.sleep(0.2)
    assert not (tmp_path / vid / "slides").exists()                      # 取消後不會留下畫面


def test_reprocess_discards_old_slides(client, tmp_path, monkeypatch):
    """重新處理後句子會變，舊的投影片畫面對不上，要丟掉（下次進投影片模式重新擷取）。"""
    vid = "aaaaaaaaaaa"
    d = _done_video(tmp_path)
    (d / "subs.json").write_text(json.dumps({"title": "T", "lang": "en", "via": "whisper", "segments": []}), encoding="utf-8")
    (d / "slides").mkdir()
    (d / "slides" / "0000.jpg").write_bytes(b"x")
    started = []
    monkeypatch.setattr(jobs, "start_job", lambda v: started.append(v) or jobs.Job(v))  # 不真的開始處理
    jobs.reprocess_video(vid)
    assert started == [vid] and not (d / "slides").exists()


def test_delete_slides_frees_space_and_they_are_captured_again_later(client, tmp_path):
    vid = "aaaaaaaaaaa"
    d = _done_video(tmp_path)
    (d / "slides").mkdir()
    times = [frames.frame_time({"start": s, "end": s + 1.0}) for s in (0.0, 1.0, 2.0)]
    (d / "slides" / "slides.json").write_text(json.dumps({"times": times, "stamp": 1}), encoding="utf-8")
    for i in range(3):
        (d / "slides" / f"{i:04d}.jpg").write_bytes(b"\xff\xd8" + b"x" * 1000)
    st = client.get(f"/api/slides/{vid}").json()
    assert st["status"] == "done" and st["bytes"] == 3 * 1002            # 確認對話框顯示佔用多少空間
    assert client.delete(f"/api/slides/{vid}").json() == {"deleted": True}
    assert not (d / "slides").exists() and (d / "translated.json").exists()  # 只刪畫面，翻譯不動
    assert client.get(f"/api/slides/{vid}").json()["status"] == "none"   # 下次進入投影片模式會重新擷取
    assert client.delete(f"/api/slides/{vid}").json() == {"deleted": False}
    assert client.delete("/api/slides/short").status_code == 400


def test_slide_image_covers_the_whole_stage_without_side_lines():
    """回歸：播放區有 1px 邊框，內部不是精確的 16:9；用 contain 左右會各留一條黑線，要用 cover。"""
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    import re
    rule = re.search(r"#slide-img\s*\{([^}]*)\}", css).group(1)
    assert "object-fit: cover" in rule
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="slide-delete"' in html and "hidden" in html[html.index('id="slide-delete"'):][:120]
