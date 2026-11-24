"""背景任務：字幕 → (Whisper) → 翻譯，並以 video_id 快取結果。"""
import json
import math
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass

from tubetran import config
from tubetran.services import frames, review, sentences, subtitles, transcribe, translate


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
                audio = transcribe.download_audio(
                    vid, cache, check, on_progress=lambda p: _set(job, "downloading_audio", p))
                check()

                def on_stage(stage: str):  # 下載模型 → 載入模型 → 解碼音檔、偵測語言 → 辨識
                    check()
                    _set(job, stage)

                def on_transcribe(p: float):
                    check()
                    _set(job, "transcribing", p)

                lang, segs = transcribe.transcribe(
                    audio, on_transcribe, on_stage,
                    on_model_progress=lambda p: _set(job, "downloading_model", p))
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
        # 繁體中文字幕常被標成 zh：看內容判斷，是繁體就改成 zh-Hant，後面各步驟（術語表、翻譯、標題）都會跳過，不呼叫 API
        data["lang"] = translate.resolve_lang(data.get("lang", ""), data["segments"])
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


# ── 書籤：存在每支影片自己的 cache/<id>/bookmarks.json，刪除快取時一併清除 ──
# 每個書籤是 {"t": 那一則字幕的開始秒數, "name": 名稱}，以時間定位（重新處理後句子會變，時間仍可對到最接近的那一句）。
# 同一個時間點只留一個書籤；依時間排序。
MAX_BOOKMARKS = 200
MAX_BOOKMARK_NAME_LEN = 40


def bookmarks_path(video_id: str):
    return config.CACHE_DIR / video_id / "bookmarks.json"


def normalize_bookmarks(items) -> list[dict]:
    """清理書籤：名稱合併空白並截斷、略過沒有名稱或時間不合法的、同一時間只留最後一個、依時間排序、限制數量。"""
    by_time: dict[float, dict] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            t = round(float(item.get("t")), 3)
        except (TypeError, ValueError):
            continue
        name = re.sub(r"\s+", " ", str(item.get("name", ""))).strip()[:MAX_BOOKMARK_NAME_LEN].strip()
        if not name or not math.isfinite(t) or t < 0:
            continue
        by_time[t] = {"t": t, "name": name}
    return [by_time[t] for t in sorted(by_time)][:MAX_BOOKMARKS]


def load_bookmarks(video_id: str) -> list[dict]:
    try:
        return normalize_bookmarks(json.loads(bookmarks_path(video_id).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def save_bookmarks(video_id: str, items) -> list[dict] | None:
    """儲存書籤並回傳清理後的結果。和標籤一樣：只有已有快取的影片才能加書籤（找不到時回傳 None）。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    if not (result_path(video_id).exists() or subs_path(video_id).exists()):
        return None
    clean = normalize_bookmarks(items)
    try:
        _write_json(bookmarks_path(video_id), clean)
    except OSError:  # 與刪除同時發生時，資料夾可能剛好消失
        return None
    return clean


# ── 術語表：cache/<id>/glossary.json（{原文: 譯法}）。翻譯時自動整理；使用者也可以手動編輯 ──
# 手動編輯過就多一個標記檔 glossary_edited.json：之後按 ↻ 重新處理時保留這份術語表，不會被自動整理的結果蓋掉。
GLOSSARY_KEY_MAX = 60
GLOSSARY_VALUE_MAX = 60


def glossary_path(video_id: str):
    return config.CACHE_DIR / video_id / "glossary.json"


def glossary_edited_path(video_id: str):
    return config.CACHE_DIR / video_id / "glossary_edited.json"


def normalize_glossary(items) -> dict[str, str]:
    """清理術語表：合併空白、截斷長度、略過原文或譯法是空的、原文忽略大小寫去重（保留最後一次的寫法）、限制數量。"""
    out: dict[str, tuple[str, str]] = {}
    pairs = items.items() if isinstance(items, dict) else items if isinstance(items, list) else []
    for pair in pairs:
        try:
            k, v = pair
        except (TypeError, ValueError):
            continue
        k = re.sub(r"\s+", " ", str(k)).strip()[:GLOSSARY_KEY_MAX].strip()
        v = re.sub(r"\s+", " ", str(v)).strip()[:GLOSSARY_VALUE_MAX].strip()
        if k and v:
            out.pop(k.casefold(), None)  # 後面的覆蓋前面的，順序也跟著挪到後面
            out[k.casefold()] = (k, v)
    return dict(list(out.values())[: translate.GLOSSARY_MAX])


def load_glossary(video_id: str) -> dict | None:
    """回傳 {"glossary": {原文: 譯法}, "edited": 是否手動編輯過}；找不到已完成的影片回傳 None。"""
    if not VIDEO_ID_RE.fullmatch(video_id) or not result_path(video_id).exists():
        return None
    g = _read_json(glossary_path(video_id)) if glossary_path(video_id).exists() else None
    if not isinstance(g, dict):  # 沒有獨立的檔案（舊快取）時，退而求其次用翻譯結果裡帶的那份
        g = (load_result(video_id) or {}).get("glossary")
    return {"glossary": normalize_glossary(g), "edited": glossary_edited_path(video_id).exists()}


def save_glossary(video_id: str, items) -> dict | None:
    """儲存手動編輯的術語表並回傳清理後的結果。只存、不重新翻譯：之後要重翻再呼叫 retranslate_video。
    找不到已完成的影片時回傳 None。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    clean = normalize_glossary(items)
    with _rw_lock:  # 和「檢查」一樣會改 translated.json
        f = result_path(video_id)
        data = _read_json(f) if f.exists() else None
        if data is None:
            return None
        try:
            _write_json(glossary_path(video_id), clean)
            _write_json(glossary_edited_path(video_id), {"edited": True})
            data["glossary"] = clean
            _write_json(f, data)
        except OSError:  # 與刪除同時發生時，資料夾可能剛好消失
            return None
    return {"glossary": clean, "edited": True}


def list_library() -> list[dict]:
    """列出快取中的影片。

    status：
      done    翻譯完成，可直接播放
      running 背景任務進行中（含取得字幕、辨識、翻譯）
      paused  曾開始翻譯但任務已中斷（例如伺服器重啟）；再次開啟會從檢查點接著翻
      error   這次執行期間任務失敗（error 欄位是原因）；重試同樣從檢查點接著翻
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
        failed = bool(job and job.status == "error")
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
            if failed:  # 這次執行期間失敗過：讓使用者知道原因，並可重試（從檢查點接著翻）
                status = stage = "error"
        items.append({
            **base, "status": status, "stage": stage, "progress": progress,
            "error": job.error if failed else "",
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
        _cancel_slides(video_id)
        job = _jobs.get(video_id)
        if job and job.status == "running":
            job.cancelled = True
            job.stage, job.progress = "cancelling", 0.0
            return "cancelling"
        _jobs.pop(video_id, None)
    shutil.rmtree(config.CACHE_DIR / video_id, ignore_errors=True)
    return "deleted"


def _cancel_slides(video_id: str) -> None:
    """要求正在準備投影片畫面的任務停下來（呼叫端持有 _lock）。它會在下一張圖之前結束並清掉 slides/。"""
    sj = _slide_jobs.pop(video_id, None)
    if sj and sj.status == "running":
        sj.cancelled = True


def reprocess_video(video_id: str) -> Job | str | None:
    """丟掉翻譯結果，重新取得字幕、重組成整句、重新翻譯。保留播放進度、標籤與書籤。

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
            doomed = [result_path(video_id), checkpoint_path(video_id),
                      result_path(video_id).with_name("translated.pre-check.json")]
            if not glossary_edited_path(video_id).exists():  # 手動編輯過的術語表保留，沒編輯過的才重新自動整理
                doomed.append(glossary_path(video_id))
            for p in doomed:
                p.unlink(missing_ok=True)
            shutil.rmtree(slides_dir(video_id), ignore_errors=True)  # 句子會變，投影片畫面要重新擷取
        _cancel_slides(video_id)
        _jobs.pop(video_id, None)
    return start_job(video_id)


def retranslate_video(video_id: str, reset_glossary: bool = False) -> Job | str | None:
    """用目前的術語表重新翻譯整支影片（字幕與句子沿用，不重新下載或辨識；標籤、書籤、播放位置、投影片都保留）。
    reset_glossary=True 時丟掉術語表（含手動編輯），重新自動整理。
    回傳新的 Job；找不到已翻譯完成的影片回傳 None；正在處理中回傳 "busy"。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    with _lock:
        job = _jobs.get(video_id)
        if job and job.status == "running":
            return "busy"
        if not (result_path(video_id).exists() and subs_path(video_id).exists()):
            return None
        with _rw_lock:
            doomed = [result_path(video_id), checkpoint_path(video_id),
                      result_path(video_id).with_name("translated.pre-check.json")]
            if reset_glossary:
                doomed += [glossary_path(video_id), glossary_edited_path(video_id)]
            for p in doomed:
                p.unlink(missing_ok=True)
        _jobs.pop(video_id, None)
    return start_job(video_id)


# ── 投影片的畫面：第一次進入投影片模式時才處理（下載影片 → 每則字幕擷取一張圖 → 刪掉影片）──
# 存在 cache/<id>/slides/：0000.jpg…，以及 slides.json（{"times": [...], "stamp": 產生時間}）。
# times 和目前字幕的時間點一致才算有效；字幕重新處理過（句子變了）就要重新擷取。
@dataclass
class SlideJob:
    video_id: str
    status: str = "running"  # running | done | error
    stage: str = "downloading_video"  # downloading_video | extracting
    progress: float = 0.0
    ready: int = 0  # 已經擷取好的張數（依字幕順序；網頁可以先用這些）
    total: int = 0
    error: str = ""
    cancelled: bool = False


_slide_jobs: dict[str, SlideJob] = {}


def slides_dir(video_id: str):
    return config.CACHE_DIR / video_id / "slides"


def _slide_times(video_id: str) -> list[float] | None:
    data = load_result(video_id)
    return [frames.frame_time(s) for s in data["segments"]] if data else None


def slide_status(video_id: str) -> dict | None:
    """投影片畫面的狀態；影片還沒翻譯完成（沒有字幕）時回傳 None。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    times = _slide_times(video_id)
    if times is None:
        return None
    job = _slide_jobs.get(video_id)
    if job and job.status != "done":
        return {**asdict(job), "stamp": 0}
    meta = _read_json(slides_dir(video_id) / "slides.json") if (slides_dir(video_id) / "slides.json").exists() else None
    if meta and meta.get("times") == times:
        size = sum(p.stat().st_size for p in slides_dir(video_id).glob("*.jpg"))
        return {"video_id": video_id, "status": "done", "stage": "done", "progress": 1.0,
                "ready": len(times), "total": len(times), "error": "", "stamp": meta.get("stamp", 0), "bytes": size}
    return {"video_id": video_id, "status": "none", "stage": "", "progress": 0.0,
            "ready": 0, "total": len(times), "error": "", "stamp": 0}


def start_slides(video_id: str) -> dict | None:
    """開始準備投影片畫面（已經好了或正在處理就不重複）。影片還沒翻譯完成時回傳 None。"""
    status = slide_status(video_id)
    if status is None or status["status"] in ("done", "running"):
        return status
    times = _slide_times(video_id)
    with _lock:
        job = _slide_jobs.get(video_id)
        if job and job.status == "running":
            return {**asdict(job), "stamp": 0}
        job = SlideJob(video_id, total=len(times))
        _slide_jobs[video_id] = job
    threading.Thread(target=_run_slides, args=(job, times), daemon=True).start()
    return {**asdict(job), "stamp": 0}


def _run_slides(job: SlideJob, times: list[float]) -> None:
    vid = job.video_id
    out = slides_dir(vid)

    def check():
        if job.cancelled:
            raise Cancelled

    def on_download(p: float):
        check()
        job.progress = p

    video = None
    try:
        shutil.rmtree(out, ignore_errors=True)  # 舊的（字幕已經變了）不要了
        out.mkdir(parents=True, exist_ok=True)
        video = frames.download_video(vid, out, check, on_download)
        job.stage, job.progress = "extracting", 0.0

        def on_frame(n: int):
            job.ready, job.progress = n, n / len(times)

        frames.extract_frames(video, times, out, on_frame, check)
        _write_json(out / "slides.json", {"times": times, "stamp": int(time.time())})
        job.status, job.stage, job.progress = "done", "done", 1.0
    except Cancelled:
        shutil.rmtree(out, ignore_errors=True)
        with _lock:
            _slide_jobs.pop(vid, None)
    except Exception as e:  # noqa: BLE001 - 回報給網頁；投影片模式照常可用（只是沒有乾淨的畫面）
        job.status, job.error = "error", f"{type(e).__name__}: {e}"[:300]
    finally:
        for p in out.glob("video.*") if out.exists() else ():  # 影片只是用來擷取畫面，擷取完（或失敗）就刪掉
            p.unlink(missing_ok=True)


def delete_slides(video_id: str) -> bool:
    """刪除這支影片的投影片畫面（正在擷取就先要求停下）。回傳原本有沒有畫面。下次進入投影片模式會重新擷取。"""
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("不合法的影片 ID")
    d = slides_dir(video_id)
    existed = d.exists()
    with _lock:
        _cancel_slides(video_id)
    shutil.rmtree(d, ignore_errors=True)
    return existed


def slide_image(video_id: str, index: int):
    """第 index 則字幕的畫面檔案；還沒擷取好時回傳 None。"""
    if not VIDEO_ID_RE.fullmatch(video_id) or not (0 <= index < 100_000):
        return None
    p = slides_dir(video_id) / f"{index:04d}.jpg"
    return p if p.exists() else None


# ── 匯出／匯入：把翻好的影片帶到其他電腦 ──
# 匯出檔是一個 JSON：{"format": "tubetran-export", "version": 1, "videos": [{"video_id": ..., "files": {檔名: 內容}}]}。
# 只帶這些檔案（都是 JSON）；音檔不帶（可能數十 MB，辨識完就用不到）。translated.json 是必要的。
EXPORT_FORMAT = "tubetran-export"
EXPORT_FILES = ("translated.json", "subs.json", "glossary.json", "glossary_edited.json",
                "progress.json", "tags.json", "bookmarks.json")


def export_bundle(video_ids: list[str] | None = None) -> dict:
    """把已翻譯完成的影片打包成匯出檔的內容。video_ids 為 None 時匯出全部；未完成的影片略過。"""
    from tubetran import __version__

    if video_ids is None:
        video_ids = [d.name for d in config.CACHE_DIR.iterdir()] if config.CACHE_DIR.exists() else []
    videos = []
    for vid in video_ids:
        if not VIDEO_ID_RE.fullmatch(vid) or not result_path(vid).exists():
            continue
        files = {}
        for name in EXPORT_FILES:
            data = _read_json(config.CACHE_DIR / vid / name) if (config.CACHE_DIR / vid / name).exists() else None
            if data is not None:
                files[name] = data
        if "translated.json" in files:
            videos.append({"video_id": vid, "files": files})
    return {"format": EXPORT_FORMAT, "version": 1, "app_version": __version__,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "videos": videos}


def import_bundle(bundle) -> dict:
    """匯入匯出檔。已經有（翻譯完成或處理中）的影片略過，不覆蓋本機的資料。
    回傳 {"imported": [...], "skipped": [...], "invalid": 筆數}；整個檔案不是匯出檔時丟出 ValueError。"""
    if not isinstance(bundle, dict) or bundle.get("format") != EXPORT_FORMAT or not isinstance(bundle.get("videos"), list):
        raise ValueError("不是水管譯工的匯出檔")
    imported, skipped, invalid = [], [], 0
    for item in bundle["videos"]:
        vid = item.get("video_id") if isinstance(item, dict) else None
        files = item.get("files") if isinstance(item, dict) else None
        if not (isinstance(vid, str) and VIDEO_ID_RE.fullmatch(vid) and isinstance(files, dict)
                and isinstance(files.get("translated.json"), dict)
                and isinstance(files["translated.json"].get("segments"), list)):
            invalid += 1
            continue
        with _lock:
            job = _jobs.get(vid)
            busy = bool(job and job.status == "running")
        if busy or result_path(vid).exists():
            skipped.append(vid)
            continue
        d = config.CACHE_DIR / vid
        d.mkdir(parents=True, exist_ok=True)
        for name in EXPORT_FILES:  # 只寫入認得的檔名，其餘忽略
            if name in files and isinstance(files[name], (dict, list)):
                _write_json(d / name, files[name])
        checkpoint_path(vid).unlink(missing_ok=True)  # 本機翻到一半的檢查點已經用不到
        imported.append(vid)
    return {"imported": imported, "skipped": skipped, "invalid": invalid}


def job_dict(job: Job) -> dict:
    return asdict(job)
