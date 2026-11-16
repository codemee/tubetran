"""背景任務：字幕 → (Whisper) → 翻譯，並以 video_id 快取結果。"""
import json
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass

from tubetran import config
from tubetran.services import review, sentences, subtitles, transcribe, translate


@dataclass
class Job:
    video_id: str
    status: str = "running"  # running | done | error
    stage: str = "queued"
    progress: float = 0.0
    done: int = 0  # 翻譯階段：已完成句數
    total: int = 0  # 翻譯階段：總句數
    error: str = ""
    cancelled: bool = False  # 使用者要求取消（並刪除）：背景任務在下一個檢查點結束，並清掉快取


class Cancelled(Exception):
    """背景任務被使用者取消。"""


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
    data.pop("fragments", None)  # 原始片段只在重新處理時用，不必送到前端
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
    if job.cancelled:  # 取消中：畫面上維持「取消中」，不要被進度更新蓋掉
        return
    job.stage, job.progress = stage, progress


def _remove_cache(path) -> None:
    """刪除快取資料夾。Windows 上剛結束的程序可能還握著檔案（例如音檔），所以失敗時稍後再試幾次。"""
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.5)


def _run(job: Job):
    vid = job.video_id
    cache = config.CACHE_DIR / vid

    def check():  # 各階段之間與每批翻譯後呼叫：被取消就丟出 Cancelled，由下面統一清理
        if job.cancelled:
            raise Cancelled

    try:
        cache.mkdir(parents=True, exist_ok=True)
        subs_file = cache / "subs.json"
        if subs_file.exists():  # 先前已取得字幕／辨識結果，直接重用
            data = json.loads(subs_file.read_text(encoding="utf-8"))
        else:
            _set(job, "fetching_subtitles")
            data = subtitles.fetch_subtitles(vid)
            check()
            if data["segments"]:
                data["via"] = data["source"]
            else:
                _set(job, "downloading_audio")
                audio = transcribe.download_audio(vid, cache, check)
                check()
                _set(job, "transcribing")

                def on_transcribe(p: float):
                    check()
                    _set(job, "transcribing", p)

                lang, segs = transcribe.transcribe(audio, on_transcribe)
                if not segs:
                    raise RuntimeError("語音辨識沒有產生任何內容")
                data.update(lang=lang, segments=segs, via="whisper")
        if data.get("unit") != "sentence":
            # 片段重組成整句再翻譯（逐段翻譯會連鎖錯位，見 services/sentences.py）。
            # 舊版留下、翻到一半的 subs.json 也在這裡轉換；它的檢查點是逐段的，對不上的句子會重新翻譯。
            # 分句前先清理片段：自動字幕常有重複的行，不先合併就會被併進同一句（變成「A A B」）
            frags, pre = review.review_segments(data.get("fragments") or data.get("segments") or [])
            data = sentences.to_sentences({**data, "fragments": frags})
            if pre["merged"] or pre["dropped"]:  # 記下來，翻譯完成時一併提示使用者
                data["pre_review"] = {"merged": pre["merged"], "dropped": pre["dropped"]}
            _write_json(subs_file, data)
        data.pop("fragments", None)  # 原始片段留在 subs.json（重新處理時用），翻譯結果不需要
        job.done, job.total = 0, len(data["segments"])
        _set(job, "translating")
        # 術語表：先讀完整支影片整理一次，之後每批都帶上，用詞才會前後一致。存起來，中斷後續翻時沿用
        gfile = cache / "glossary.json"
        glossary = _read_json(gfile) if gfile.exists() else None
        if not isinstance(glossary, dict):
            glossary = translate.make_glossary(data["segments"], data["lang"], data["title"])
            check()
            _write_json(gfile, glossary)
        data["glossary"] = glossary
        checkpoint = cache / "trans_partial.json"

        def on_translate(done: int, total: int):
            check()
            job.done = done
            _set(job, "translating", done / total)

        data["segments"] = translate.translate_segments(
            data["segments"],
            data["lang"],
            data["title"],
            on_progress=on_translate,
            checkpoint=checkpoint,
            glossary=glossary,
        )
        # 翻譯完成後自動檢查一輪：修正重複與時序錯亂（本機規則，不呼叫 API）
        data["segments"], report = review.review_segments(data["segments"])
        for k, n in (data.pop("pre_review", None) or {}).items():  # 分句前清理片段時的修正
            report[k] += n
        if review.changed(report):
            data["review"] = report  # 只在真的修正過時記錄，前端才會提示
        try:  # 標題翻譯失敗不影響整體結果
            data["title_trans"] = translate.translate_title(data["title"], data["lang"], glossary=glossary)
        except Exception:  # noqa: BLE001
            data["title_trans"] = ""
        data["video_id"] = vid
        check()
        _write_json(result_path(vid), data)
        # 最終結果寫好之後才刪檢查點，中間不會出現「兩邊都沒有」的空窗
        checkpoint.unlink(missing_ok=True)
        with _lock:  # 與 delete_video 互斥：要嘛在這之前被取消（清掉剛寫的結果），要嘛已完成、之後當一般影片刪除
            if job.cancelled:
                raise Cancelled
            job.status, job.stage, job.progress = "done", "done", 1.0
    except Cancelled:
        _remove_cache(cache)
        with _lock:
            _jobs.pop(vid, None)
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


# ── 標籤：存在每支影片自己的 cache/<id>/tags.json，刪除快取時一併清除 ──
MAX_TAGS = 10
MAX_TAG_LEN = 20


def tags_path(video_id: str):
    return config.CACHE_DIR / video_id / "tags.json"


def normalize_tags(tags) -> list[str]:
    """清理標籤：合併空白、截斷長度、忽略大小寫去重（保留第一次出現的寫法）、限制數量。"""
    out, seen = [], set()
    for raw in tags:
        tag = re.sub(r"\s+", " ", str(raw)).strip()[:MAX_TAG_LEN].strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:MAX_TAGS]


def load_tags(video_id: str) -> list[str]:
    try:
        d = json.loads(tags_path(video_id).read_text(encoding="utf-8"))
        return normalize_tags(d if isinstance(d, list) else [])
    except (OSError, ValueError):
        return []


def save_tags(video_id: str, tags) -> list[str] | None:
    """儲存標籤並回傳清理後的結果。只有已有快取的影片才能加標籤（找不到時回傳 None），
    避免替已刪除的影片重建資料夾。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    if not (result_path(video_id).exists() or subs_path(video_id).exists()):
        return None
    clean = normalize_tags(tags)
    try:
        _write_json(tags_path(video_id), clean)
    except OSError:  # 與刪除同時發生時，資料夾可能剛好消失
        return None
    return clean


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
            "tags": load_tags(vid),
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
                segs, n = translate.repair_missing(segs, data.get("lang", ""), data.get("title", ""),
                                                   glossary=data.get("glossary"))
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


def delete_video(video_id: str) -> str:
    """清除該影片的整個快取資料夾；不存在也視為成功，回傳 "deleted"。

    處理中的影片不能直接刪（任務還在寫檔）：改成要求任務取消，回傳 "cancelling"。
    任務會在下一個檢查點（約一批翻譯、一小段辨識之後）自己結束並清掉快取資料夾。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    with _lock:
        job = _jobs.get(video_id)
        if job and job.status == "running":
            job.cancelled = True
            job.stage, job.progress = "cancelling", 0.0
            return "cancelling"
        _jobs.pop(video_id, None)
    shutil.rmtree(config.CACHE_DIR / video_id, ignore_errors=True)
    return "deleted"


def reprocess_video(video_id: str) -> Job | str | None:
    """丟掉翻譯結果，重新取得字幕、重組成整句、重新翻譯。保留播放進度與標籤。

    - 字幕來自 YouTube（人工／自動）：刪掉 subs.json 重新抓（免費，而且能拿到逐字時間）。
    - 字幕來自 Whisper：保留辨識結果（重跑很慢），只用原始片段重新分句。
    回傳新的 Job；找不到這支影片回傳 None；正在處理中回傳 "busy"。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    with _lock:
        job = _jobs.get(video_id)
        if job and job.status == "running":
            return "busy"
        if not (result_path(video_id).exists() or subs_path(video_id).exists()):
            return None
        with _rw_lock:  # 不要和「檢查」、背景補翻標題同時改檔
            subs = _read_json(subs_path(video_id)) if subs_path(video_id).exists() else None
            if subs and subs.get("via") == "whisper":
                subs["segments"] = subs.get("fragments") or subs.get("segments") or []
                subs.pop("fragments", None)
                subs.pop("unit", None)
                _write_json(subs_path(video_id), subs)
            else:
                subs_path(video_id).unlink(missing_ok=True)
            for p in (result_path(video_id), checkpoint_path(video_id),
                      result_path(video_id).with_name("translated.pre-check.json"),
                      result_path(video_id).with_name("glossary.json")):
                p.unlink(missing_ok=True)
        _jobs.pop(video_id, None)
    return start_job(video_id)


def job_dict(job: Job) -> dict:
    return asdict(job)
