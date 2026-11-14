"""背景任務：字幕 → (Whisper) → 翻譯，並以 video_id 快取結果。"""
import json
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass

from app import config
from app.services import review, subtitles, transcribe, translate


@dataclass
class Job:
    video_id: str
    status: str = "running"  # running | done | error
    stage: str = "queued"
    progress: float = 0.0
    done: int = 0  # 翻譯階段：已完成句數
    total: int = 0  # 翻譯階段：總句數
    error: str = ""


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def _write_json(path, data) -> None:
    """原子寫入：先寫暫存檔再取代，避免讀取端（影片庫、前端輪詢）看到寫到一半的檔案。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def result_path(video_id: str):
    return config.CACHE_DIR / video_id / "translated.json"


def subs_path(video_id: str):
    return config.CACHE_DIR / video_id / "subs.json"


def checkpoint_path(video_id: str):
    return config.CACHE_DIR / video_id / "trans_partial.json"


def load_result(video_id: str) -> dict | None:
    if not VIDEO_ID_RE.fullmatch(video_id):
        return None
    p = result_path(video_id)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def load_subtitles(video_id: str) -> dict | None:
    """回傳字幕資料。翻譯完成時 complete=True；翻譯進行中則合併檢查點，
    已翻好的句子帶 trans、其餘不帶，complete=False，讓前端可以先使用部分譯文。"""
    full = load_result(video_id)
    if full:
        return {**full, "complete": True}
    if not VIDEO_ID_RE.fullmatch(video_id):
        return None
    try:
        data = json.loads(subs_path(video_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cp = translate.load_checkpoint(checkpoint_path(video_id))
    segs, n = [], 0
    for i, s in enumerate(data["segments"]):
        s = dict(s)
        saved = cp.get(str(i))
        if saved and saved[0] == s["text"]:
            s["trans"], n = saved[1], n + 1
        segs.append(s)
    return {**data, "segments": segs, "video_id": video_id, "complete": False, "translated": n}


def get_job(video_id: str) -> Job | None:
    return _jobs.get(video_id)


def start_job(video_id: str) -> Job:
    with _lock:
        job = _jobs.get(video_id)
        if job and job.status == "running":
            return job
        if load_result(video_id):
            job = Job(video_id, "done", "cached", 1.0)
            _jobs[video_id] = job
            return job
        job = Job(video_id)
        _jobs[video_id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def _set(job: Job, stage: str, progress: float = 0.0):
    job.stage, job.progress = stage, progress


def _run(job: Job):
    vid = job.video_id
    cache = config.CACHE_DIR / vid
    try:
        cache.mkdir(parents=True, exist_ok=True)
        subs_file = cache / "subs.json"
        if subs_file.exists():  # 先前已取得字幕／辨識結果，直接重用
            data = json.loads(subs_file.read_text(encoding="utf-8"))
        else:
            _set(job, "fetching_subtitles")
            data = subtitles.fetch_subtitles(vid)
            if data["segments"]:
                data["via"] = data["source"]
            else:
                _set(job, "downloading_audio")
                audio = transcribe.download_audio(vid, cache)
                _set(job, "transcribing")
                lang, segs = transcribe.transcribe(
                    audio, lambda p: _set(job, "transcribing", p)
                )
                if not segs:
                    raise RuntimeError("語音辨識沒有產生任何內容")
                data.update(lang=lang, segments=segs, via="whisper")
            _write_json(subs_file, data)
        job.done, job.total = 0, len(data["segments"])
        _set(job, "translating")
        checkpoint = cache / "trans_partial.json"

        def on_translate(done: int, total: int):
            job.done = done
            _set(job, "translating", done / total)

        data["segments"] = translate.translate_segments(
            data["segments"],
            data["lang"],
            data["title"],
            on_progress=on_translate,
            checkpoint=checkpoint,
        )
        # 翻譯完成後自動檢查一輪：修正重複與時序錯亂（本機規則，不呼叫 API）
        data["segments"], report = review.review_segments(data["segments"])
        if review.changed(report):
            data["review"] = report  # 只在真的修正過時記錄，前端才會提示
        try:  # 標題翻譯失敗不影響整體結果
            data["title_trans"] = translate.translate_title(data["title"], data["lang"])
        except Exception:  # noqa: BLE001
            data["title_trans"] = ""
        data["video_id"] = vid
        _write_json(result_path(vid), data)
        # 最終結果寫好之後才刪檢查點，中間不會出現「兩邊都沒有」的空窗
        checkpoint.unlink(missing_ok=True)
        job.status, job.stage, job.progress = "done", "done", 1.0
    except Exception as e:  # noqa: BLE001 - 任何錯誤都回報給前端
        job.status, job.error = "error", f"{type(e).__name__}: {e}"


def progress_path(video_id: str):
    return config.CACHE_DIR / video_id / "progress.json"


def save_progress(video_id: str, position: float, duration: float) -> bool:
    """記錄播放位置。只有已有快取（字幕已取得或已翻譯）的影片才會記錄，
    避免替已刪除的影片重建資料夾。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    if not (result_path(video_id).exists() or subs_path(video_id).exists()):
        return False
    try:
        _write_json(
            progress_path(video_id),
            {"position": position, "duration": duration, "updated": time.time()},
        )
    except OSError:  # 與刪除同時發生時，資料夾可能剛好消失
        return False
    return True


def load_progress(video_id: str) -> dict:
    p = progress_path(video_id)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"position": float(d.get("position", 0)), "duration": float(d.get("duration", 0))}
    except (OSError, ValueError, TypeError):
        return {"position": 0.0, "duration": 0.0}


def resume_position(p: dict) -> float:
    """下次開啟時該從哪裡開始：太接近開頭或結尾就從頭看。"""
    pos, dur = p["position"], p["duration"]
    if pos < 5 or (dur and pos > dur - 10):
        return 0.0
    return pos


def _read_json(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_library() -> list[dict]:
    """列出快取中的影片。

    status：
      done    翻譯完成，可直接播放
      running 背景任務進行中（含取得字幕、辨識、翻譯）
      paused  曾開始翻譯但任務已中斷（例如伺服器重啟）；再次開啟會從檢查點接著翻
    處理中與中斷的排在最前面，其餘依完成時間新到舊。
    """
    items = []
    if not config.CACHE_DIR.exists():
        return items
    for d in config.CACHE_DIR.iterdir():
        vid = d.name
        if not (d.is_dir() and VIDEO_ID_RE.fullmatch(vid)):
            continue
        job = _jobs.get(vid)
        running = bool(job and job.status == "running")
        prog = load_progress(vid)
        base = {
            "video_id": vid,
            "position": resume_position(prog),
            "duration": prog["duration"],
            "stage": "done",
            "progress": 1.0,
        }
        f = result_path(vid)
        data = _read_json(f) if f.exists() else None
        if data is not None:
            items.append({
                **base, "status": "done",
                "title": data.get("title", vid),
                "title_trans": data.get("title_trans"),  # None 代表尚未翻譯（舊快取）
                "lang": data.get("lang", ""), "via": data.get("via", ""),
                "count": len(data.get("segments", [])),
                "mtime": f.stat().st_mtime,
            })
            continue
        subs = _read_json(subs_path(vid)) if subs_path(vid).exists() else None
        if not running and not subs:
            continue  # 只剩殘留檔案（例如音檔）的資料夾，不列出
        total = len(subs["segments"]) if subs else 0
        if running:
            status, stage = "running", job.stage
            progress = job.progress if stage == "translating" else 0.0
        else:
            cp = translate.load_checkpoint(checkpoint_path(vid))
            done = sum(
                1 for i, s in enumerate(subs["segments"])
                if (c := cp.get(str(i))) and c[0] == s["text"]
            )
            status, stage, progress = "paused", "paused", (done / total if total else 0.0)
        items.append({
            **base, "status": status, "stage": stage, "progress": progress,
            "title": subs["title"] if subs else vid,
            "title_trans": "",  # 處理中的影片不補翻標題，完成後流程會一併翻譯
            "lang": subs.get("lang", "") if subs else "",
            "via": subs.get("via", "") if subs else "",
            "count": total,
            "mtime": (subs_path(vid).stat().st_mtime if subs else d.stat().st_mtime),
        })
    return sorted(items, key=lambda x: (x["status"] == "done", -x["mtime"]))


_rw_lock = threading.Lock()  # 保護 translated.json 的「讀取→修改→寫回」，避免同時寫入時互相覆蓋


def check_video(video_id: str) -> dict | None:
    """對已完成的影片重新檢查字幕（合併重複、修正時序）。找不到已完成的字幕時回傳 None。
    只有真的有修正時才寫回；第一次修改前會備份成 translated.pre-check.json。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    with _rw_lock:
        f = result_path(video_id)
        data = _read_json(f) if f.exists() else None
        if data is None:
            return None
        segs, report = review.review_segments(data.get("segments", []))
        did_change = review.changed(report)
        report["repaired"] = 0
        if report["untranslated"]:  # 有空白譯文：呼叫 Claude 補翻（只翻缺的那幾句）
            try:
                segs, n = translate.repair_missing(segs, data.get("lang", ""), data.get("title", ""))
                report["repaired"] = n
                report["untranslated"] = sum(1 for s in segs if not (s.get("trans") or "").strip())
                did_change = did_change or n > 0
            except Exception as e:  # noqa: BLE001 - 補翻失敗不影響其他檢查結果，回報讓使用者知道
                report["repair_error"] = f"{type(e).__name__}: {e}"[:200]
        if did_change:
            backup = f.with_name("translated.pre-check.json")
            if not backup.exists():
                shutil.copyfile(f, backup)
            data["segments"] = segs
            data["review"] = report
            _write_json(f, data)
    return {**report, "changed": did_change}


_backfilling: set[str] = set()


def backfill_titles(items: list[dict]) -> None:
    """替沒有 title_trans 的舊快取在背景補翻標題（每支影片一次短短的 API 呼叫）。"""
    todo = []
    with _lock:
        for it in items:
            if (
                it["status"] == "done"
                and it["title_trans"] is None
                and it["video_id"] not in _backfilling
            ):
                _backfilling.add(it["video_id"])
                todo.append(it)
    if todo:
        threading.Thread(target=_backfill_worker, args=(todo,), daemon=True).start()


def _backfill_worker(todo: list[dict]) -> None:
    for it in todo:
        vid = it["video_id"]
        try:
            trans = translate.translate_title(it["title"], it["lang"])
            f = result_path(vid)
            with _rw_lock:
                if f.exists():  # 期間若被使用者刪除就不要寫回
                    data = json.loads(f.read_text(encoding="utf-8"))
                    data["title_trans"] = trans
                    _write_json(f, data)
        except Exception:  # noqa: BLE001 - 失敗就保留原標題，下次載入影片庫再試
            pass
        finally:
            with _lock:
                _backfilling.discard(vid)


def delete_video(video_id: str) -> bool:
    """清除該影片的整個快取資料夾。處理中回傳 False；不存在也視為成功。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    with _lock:
        job = _jobs.get(video_id)
        if job and job.status == "running":
            return False
        _jobs.pop(video_id, None)
    shutil.rmtree(config.CACHE_DIR / video_id, ignore_errors=True)
    return True


def job_dict(job: Job) -> dict:
    return asdict(job)
