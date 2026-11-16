import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tubetran import config, jobs, settings
from tubetran.services import export, subtitles


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 沒有 API 金鑰也要能啟動：使用者可以在介面的設定面板輸入；真正需要時（/api/process）才檢查
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="TubeTran", lifespan=lifespan)


class ProcessReq(BaseModel):
    url: str


@app.post("/api/process")
def process(req: ProcessReq):
    vid = subtitles.parse_video_id(req.url)
    if not vid:
        raise HTTPException(400, "無法從網址解析 YouTube 影片 ID")
    if not jobs.load_result(vid):  # 已翻譯完成的影片只是重新播放，不需要金鑰
        try:
            config.get_api_key()  # 先檢查，免得下載、辨識做到一半才發現無法翻譯
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    started = jobs.start_job(vid)
    if started.cancelled:  # 上一個任務還在取消、清理中：現在重開會和它搶同一個資料夾
        raise HTTPException(409, "這支影片正在取消中，請稍後再試")
    job = jobs.job_dict(started)
    resume = jobs.resume_position(jobs.load_progress(vid))
    return {"video_id": vid, **job, "position": resume}


class ProgressReq(BaseModel):
    position: float = Field(ge=0, le=1_000_000)
    duration: float = Field(default=0, ge=0, le=1_000_000)


@app.put("/api/progress/{video_id}")
def put_progress(video_id: str, req: ProgressReq):
    try:
        saved = jobs.save_progress(video_id, req.position, req.duration)
    except ValueError:
        raise HTTPException(400, "不合法的影片 ID")
    return {"saved": saved}


@app.get("/api/library")
def library():
    items = jobs.list_library()
    jobs.backfill_titles(items)  # 舊快取缺少譯名時，背景補翻，下次載入即可看到
    return items


@app.delete("/api/library/{video_id}")
def delete_library_item(video_id: str):
    try:
        result = jobs.delete_video(video_id)
    except ValueError:
        raise HTTPException(400, "不合法的影片 ID")
    if result == "cancelling":  # 處理中：已要求任務取消，它結束後會自己清掉快取
        return JSONResponse({"cancelling": video_id}, status_code=202)
    return {"deleted": video_id}


class TagsReq(BaseModel):
    tags: list[str] = Field(max_length=50)


@app.put("/api/library/{video_id}/tags")
def put_tags(video_id: str, req: TagsReq):
    try:
        tags = jobs.save_tags(video_id, req.tags)
    except ValueError:
        raise HTTPException(400, "不合法的影片 ID")
    if tags is None:
        raise HTTPException(404, "找不到這支影片")
    return {"tags": tags}


@app.post("/api/library/{video_id}/check")
def check_library_item(video_id: str):
    try:
        report = jobs.check_video(video_id)
    except ValueError:
        raise HTTPException(400, "不合法的影片 ID")
    if report is None:
        raise HTTPException(404, "找不到已完成的字幕")
    return report


@app.get("/api/jobs/{video_id}")
def job_status(video_id: str):
    job = jobs.get_job(video_id)
    if not job:
        raise HTTPException(404, "找不到任務")
    return jobs.job_dict(job)


@app.get("/api/subtitles/{video_id}.{fmt}")
def download_subtitles(video_id: str, fmt: str, mode: str = "both"):
    if fmt not in ("srt", "vtt") or mode not in ("orig", "trans", "both"):
        raise HTTPException(400, "不支援的格式或模式")
    data = jobs.load_result(video_id)
    if not data:
        raise HTTPException(404, "字幕尚未準備好")
    fn = export.to_srt if fmt == "srt" else export.to_vtt
    return PlainTextResponse(
        fn(data["segments"], mode),
        headers={"Content-Disposition": f'attachment; filename="{video_id}.{mode}.{fmt}"'},
    )


@app.get("/api/subtitles/{video_id}")
def get_subtitles(video_id: str):
    # 翻譯進行中也會回傳：已翻好的句子帶 trans，complete=False
    data = jobs.load_subtitles(video_id)
    if not data:
        raise HTTPException(404, "字幕尚未準備好")
    return data


class SettingsReq(BaseModel):
    # 欄位為 null 表示不變；api_key 為空字串也表示不變（介面只會顯示遮罩後的金鑰，沒有重新輸入就不送）
    api_key: str | None = Field(default=None, max_length=400)
    translate_model: str | None = Field(default=None, max_length=100)
    whisper_model: str | None = Field(default=None, max_length=100)


@app.get("/api/settings")
def get_settings():
    return settings.current()


@app.put("/api/settings")
def put_settings(req: SettingsReq):
    try:
        return settings.update(req.api_key, req.translate_model, req.whisper_model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError:
        raise HTTPException(500, "無法寫入設定檔（settings.json），請檢查資料資料夾的權限")


@app.get("/api/models")
def get_models():
    """兩個下拉選單的選項：翻譯模型向 Anthropic 查詢（需要有效金鑰），STT 模型取自 faster-whisper。"""
    return {"translate": settings.translate_models(), "whisper": settings.whisper_models()}


# 前端檔案每次都要向伺服器確認有沒有更新（沒變就回 304，很便宜）。
# 沒有這個標頭時，瀏覽器會依「檔案多久沒改」自行猜一段可以不重新確認的時間；桌面版的 WebView
# 又把快取存在資料資料夾，升級之後可能一直用舊的 JS／CSS，和新的後端對不上。
NO_CACHE = {"Cache-Control": "no-cache"}


class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        config.STATIC_DIR / "logo" / "tubetran-light-icon.svg", media_type="image/svg+xml", headers=NO_CACHE
    )


def asset_version() -> str:
    """前端檔案的內容版本：任何一個檔案的大小或修改時間變了，它就會變。每次請求重算（約十個檔案，很便宜），
    所以開發時改了檔案、重新整理就生效，升級後也一定是新網址。"""
    import hashlib

    h = hashlib.sha1()
    for p in sorted(config.STATIC_DIR.rglob("*")):
        if p.is_file() and p.suffix in (".js", ".css", ".html"):
            st = p.stat()
            h.update(f"{p.relative_to(config.STATIC_DIR)}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:10]


_ASSET_URL = re.compile(r'((?:src|href)="/static/[^"?]+\.(?:js|css))"')


@app.get("/")
def index():
    """首頁：腳本與樣式表的網址帶上內容版本（?v=…），舊的快取就用不上，一定拿到新檔。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = _ASSET_URL.sub(rf'\1?v={asset_version()}"', html)
    return HTMLResponse(html, headers=NO_CACHE)


app.mount("/static", _NoCacheStaticFiles(directory=config.STATIC_DIR), name="static")
