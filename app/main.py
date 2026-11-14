from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config, jobs
from app.services import export, subtitles


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.get_api_key()  # 缺少 key 時啟動即報錯
    config.CACHE_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(title="trantube", lifespan=lifespan)


class ProcessReq(BaseModel):
    url: str


@app.post("/api/process")
def process(req: ProcessReq):
    vid = subtitles.parse_video_id(req.url)
    if not vid:
        raise HTTPException(400, "無法從網址解析 YouTube 影片 ID")
    job = jobs.job_dict(jobs.start_job(vid))
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
        ok = jobs.delete_video(video_id)
    except ValueError:
        raise HTTPException(400, "不合法的影片 ID")
    if not ok:
        raise HTTPException(409, "這支影片正在處理中，請稍後再刪除")
    return {"deleted": video_id}


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(
        config.STATIC_DIR / "logo" / "tubetran-rx78-light-icon.svg", media_type="image/svg+xml"
    )


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
