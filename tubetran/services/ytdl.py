"""yt-dlp 的共用設定。

YouTube 的影音網址要解一道 JavaScript 驗證（n 參數）才會讓你完整下載；yt-dlp 需要外部的 JS 執行環境
（deno／node／bun）加上 yt-dlp-ejs 的腳本來解。沒有的話 yt-dlp 仍可運作，但 YouTube 偶爾會在下載途中
回 HTTP 403（實測：同一支影片有時成功、有時失敗）。

所以：電腦上找得到哪個 JS 執行環境就交給 yt-dlp 用；找不到時照舊，下載音檔另有自動重試（transcribe.py）。
字幕不受影響：字幕檔不是影音串流，不需要解驗證。
"""
import shutil

JS_RUNTIMES = ("deno", "node", "bun")  # yt-dlp 支援的執行環境；deno 是官方建議


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
