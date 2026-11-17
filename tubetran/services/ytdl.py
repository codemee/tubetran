"""yt-dlp 的共用設定。

YouTube 的影音網址要解一道 JavaScript 驗證（n 參數）才會讓你完整下載；yt-dlp 需要外部的 JS 執行環境
（deno／node／bun）加上 yt-dlp-ejs 的腳本來解。沒有的話 yt-dlp 仍可運作，但 YouTube 偶爾會在下載途中
回 HTTP 403（實測：同一支影片有時成功、有時失敗）。

所以：電腦上找得到哪個 JS 執行環境就交給 yt-dlp 用；找不到時照舊，下載音檔另有自動重試（transcribe.py）。
字幕不受影響：字幕檔不是影音串流，不需要解驗證。
"""
import shutil
import time
from pathlib import Path
from typing import Callable

import yt_dlp

JS_RUNTIMES = ("deno", "node", "bun")  # yt-dlp 支援的執行環境；deno 是官方建議
DOWNLOAD_ATTEMPTS = 3
RETRY_WAIT = 2.0  # 秒；每次重試多等一點
PARTIAL_SUFFIXES = (".part", ".ytdl", ".tmp")  # yt-dlp 下載到一半的暫存檔


def js_runtimes() -> dict:
    """電腦上找得到的 JS 執行環境，格式同 yt-dlp 的 js_runtimes 選項；都沒有時回傳空的。"""
    return {name: {"path": path} for name in JS_RUNTIMES if (path := shutil.which(name))}


def base_opts() -> dict:
    """所有 yt-dlp 呼叫共用的選項。"""
    opts = {"quiet": True, "no_warnings": True}
    runtimes = js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts


def finished_file(out_dir: Path, stem: str) -> Path | None:
    """已下載完成的 <stem>.*（不含下載到一半的暫存檔）。"""
    return next((p for p in out_dir.glob(f"{stem}.*") if p.suffix not in PARTIAL_SUFFIXES), None)


def download_media(
    video_id: str,
    out_dir: Path,
    stem: str,
    fmt: str,
    check: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path | None:
    """下載影片的音訊或影像（yt-dlp 的格式選擇 fmt），存成 out_dir/<stem>.<副檔名>；已經有就直接用。

    check：下載過程中不斷呼叫，丟出例外就中止下載（用來取消任務）。
    on_progress：下載進度（0～1），yt-dlp 知道檔案大小時才會回報。
    YouTube 偶爾會在下載途中回 HTTP 403（電腦上沒有 JS 執行環境時尤其常見）。每次重試都重新向 YouTube
    取得下載網址，通常第二次就會成功。回傳下載好的檔案；yt-dlp 沒有產生檔案時回傳 None。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = finished_file(out_dir, stem)
    if existing:
        return existing

    def hook(d: dict) -> None:
        if check:
            check()
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if on_progress and total and d.get("downloaded_bytes") is not None:
            on_progress(min(d["downloaded_bytes"] / total, 1.0))

    opts = {**base_opts(), "format": fmt, "outtmpl": str(out_dir / f"{stem}.%(ext)s"), "progress_hooks": [hook]}
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            break
        except yt_dlp.utils.DownloadError:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            if check:
                check()  # 等待前先看看是不是已被取消
            time.sleep(RETRY_WAIT * attempt)
    return finished_file(out_dir, stem)
