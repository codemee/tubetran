"""投影片模式的畫面：下載影片（只要影像、1080p 優先），在每則字幕的時間點擷取一張 JPEG。

為什麼：YouTube 嵌入播放器暫停（甚至播放）時一定會疊上播放鈕、標題列等介面，參數關不掉。
自己擷取的畫面完全乾淨，而且切換是即時的（只是換一張圖），也能離線使用。
擷取完就刪掉影片檔，只留圖片（10 分鐘的影片約 200 張、20～30 MB）。
"""
from pathlib import Path
from typing import Callable

from tubetran.services import ytdl

# 1080p 優先：同畫質先選 H.264（解碼最快、檔案通常最小），再來是其他編碼；沒有 1080p 才退到較低畫質。
# 優先用 https 直連的串流（m3u8 分段下載較慢、檔案也較大）。
VIDEO_FORMAT = (
    "bestvideo[height<=1080][vcodec^=avc1][protocol^=http]"
    "/bestvideo[height<=1080][protocol^=http]"
    "/bestvideo[height<=1080]"
    "/best[height<=1080]"
    "/best"
)
SEEK_GAP = 4.0  # 下一個時間點離目前解碼位置超過這麼多秒才跳轉（較近的直接往下解碼比較快）


END_MARGIN = 0.25  # 擷取字幕結束前多少秒的畫面


def frame_time(seg: dict) -> float:
    """某則字幕要擷取的時間點：結束前一點點（END_MARGIN 秒），但不早於這則的中間（很短的句子）。

    為什麼不用開始的那一格：影片常在一句話開始時轉場（淡入、逐字打出），開始那一格畫面還沒完整，
    看起來像蒙了一層或只出現一半。結束前畫面已經完整，也還沒進入下一句的轉場。"""
    start, end = float(seg["start"]), float(seg["end"])
    return round(max((start + end) / 2, end - END_MARGIN), 3)


def download_video(
    video_id: str,
    out_dir: Path,
    check: Callable[[], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """下載影片的影像（不含聲音），存成 out_dir/video.*。"""
    path = ytdl.download_media(video_id, out_dir, "video", VIDEO_FORMAT, check, on_progress)
    if not path:
        raise RuntimeError("影片下載失敗")
    return path


def extract_frames(
    video: Path,
    times: list[float],
    out_dir: Path,
    on_frame: Callable[[int], None] | None = None,
    check: Callable[[], None] | None = None,
) -> int:
    """依序在每個時間點擷取一張畫面，存成 out_dir/0000.jpg、0001.jpg……（編號＝字幕的序號）。
    每存好一張呼叫 on_frame(已完成張數)，網頁可以先用已經好的。回傳擷取到的張數。
    時間點超過影片長度時，用最後一格。JPEG 由 PyAV 內建的 mjpeg 編碼器產生，不需要其他套件。"""
    import av

    out_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        tb = stream.time_base
        encoder = None
        frames = None
        pos = float("-inf")  # 目前解碼到的時間
        last = None          # 最近解出來的一格
        for i, t in enumerate(times):
            if check:
                check()
            if frames is None or t < pos or t - pos > SEEK_GAP:
                container.seek(max(0, int(t / tb)), stream=stream, backward=True)  # 跳到前一個關鍵畫格
                frames = container.decode(stream)
                last = None
            for f in frames:  # 往下解碼到 t（含）為止
                last = f
                pos = float(f.pts * tb) if f.pts is not None else pos
                if pos + 1e-3 >= t:
                    break
            if last is None:
                continue
            if encoder is None:
                encoder = av.CodecContext.create("mjpeg", "w")
                encoder.width, encoder.height = last.width, last.height
                encoder.pix_fmt = "yuvj420p"
                # 時間單位要和畫格相同：不同的話 PyAV 會換算時間戳記，細的單位換到粗的會四捨五入成同一個值，
                # 編碼器就拒絕（avcodec_send_frame 回傳 EINVAL）
                encoder.time_base = tb
                # 畫質：預設的壓縮會讓投影片上的小字糊掉。qmin 2／qmax 3 每張約 80 KB（1080p），小字清楚
                encoder.options = {"qmin": "2", "qmax": "3"}
            img = last.reformat(format="yuvj420p")
            img.pts = done  # 編碼器要求時間戳記遞增；時間點偶爾會往回（例如句子順序調整過），所以用序號
            img.time_base = tb
            jpeg = b"".join(bytes(p) for p in encoder.encode(img))
            tmp = out_dir / f"{i:04d}.jpg.tmp"
            tmp.write_bytes(jpeg)
            tmp.replace(out_dir / f"{i:04d}.jpg")  # 原子寫入：網頁不會讀到寫一半的圖
            done += 1
            if on_frame:
                on_frame(done)
    return done
