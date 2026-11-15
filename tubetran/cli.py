"""命令列入口：同一個程式、兩種模式。

    tubetran                                  桌面模式：開啟視窗（內部在背景執行緒啟動後端）
    tubetran --server [--host H] [--port P]   伺服器模式：不開視窗，只啟動後端

整個程式是單一程序：桌面模式的後端是這個程序裡的一條執行緒，視窗關閉、程序結束，
後端就一起結束，不會留下孤兒程序。
"""
import argparse
import ctypes
import json
import multiprocessing
import socket
import sys
import threading
import time

from tubetran import config

WINDOW_TITLE = "水管譯工"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tubetran",
        description="水管譯工 (TubeTran)：不加參數開啟桌面視窗；加上 --server 則以伺服器模式執行。",
    )
    p.add_argument("--server", action="store_true",
                   help="伺服器模式：不開視窗，只啟動後端（Ctrl+C 結束）")
    p.add_argument("--host", default="127.0.0.1",
                   help="伺服器模式的監聽位址，預設 127.0.0.1（要讓區網其他裝置連線請用 0.0.0.0）")
    p.add_argument("--port", type=int, default=8000, help="伺服器模式的埠號，預設 8000")
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)  # 檢查打包是否完整
    return p


def _setup_streams(cli_use: bool) -> None:
    """打包成視窗程式（沒有主控台）時，sys.stdout／stderr 會是 None，print 與 logging 都會出錯。

    - 有帶參數（命令列用法）：附著到啟動它的終端機，輸出顯示在那裡。
    - 仍然沒有輸出管道（例如雙擊啟動）：改寫到資料資料夾的 tubetran.log。
    """
    if sys.platform == "win32" and cli_use and (sys.stdout is None or sys.stderr is None):
        try:
            if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
                if sys.stdout is None:
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
                if sys.stderr is None:
                    sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        except OSError:
            pass
    if sys.stdout is None or sys.stderr is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(config.DATA_DIR / "tubetran.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def selftest() -> int:
    """列出各依賴能否載入，用來確認打包後的執行檔沒有漏東西。"""
    import importlib
    import os

    out: dict = {}
    for name in ("fastapi", "uvicorn", "yt_dlp", "anthropic", "faster_whisper",
                 "ctranslate2", "av", "onnxruntime", "webview"):
        try:
            mod = importlib.import_module(name)
            out[name] = getattr(mod, "__version__", "ok")
        except Exception as e:  # noqa: BLE001
            out[name] = f"FAIL: {type(e).__name__}: {e}"
    try:
        from faster_whisper.utils import get_assets_path
        out["whisper_vad_assets"] = sorted(os.listdir(get_assets_path()))
    except Exception as e:  # noqa: BLE001
        out["whisper_vad_assets"] = f"FAIL: {type(e).__name__}: {e}"
    out.update(
        frozen=config.FROZEN,
        data_dir=str(config.DATA_DIR),
        static_index_found=(config.STATIC_DIR / "index.html").exists(),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if any(str(v).startswith("FAIL") for v in out.values()) else 0


def run_server(host: str, port: int) -> int:
    import uvicorn

    from tubetran.main import app

    print(f"{WINDOW_TITLE} 伺服器模式：http://{host}:{port}/  （Ctrl+C 結束）", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


# 桌面模式優先使用固定埠：localStorage（主題、語言設定）是依「來源 = 協定＋主機＋埠號」區分的，
# 每次都換埠號，設定就會在下次啟動時消失。只有這個埠被占用（例如開了第二個視窗）才退回隨機埠。
DESKTOP_PORT = 47321


def _pick_port() -> int:
    for candidate in (DESKTOP_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError("找不到可用的埠號")


class _BackgroundServer:
    """在背景執行緒執行 uvicorn（桌面模式用）。"""

    def __init__(self, port: int):
        import uvicorn

        from tubetran.main import app

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
        self.thread = threading.Thread(target=self.server.run, name="backend", daemon=True)

    def start(self, timeout: float = 90) -> bool:
        self.thread.start()
        end = time.time() + timeout
        while time.time() < end:
            if self.server.started:
                return True
            if not self.thread.is_alive():  # 啟動失敗（例如埠號被占用）
                return False
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class _DesktopApi:
    """提供給網頁呼叫的橋接（window.pywebview.api）。

    網頁的 element.requestFullscreen() 在 pywebview 裡只會讓「網頁內容」填滿視窗，
    視窗的標題列與邊框仍在；所以網頁進入／離開全螢幕時，要同步讓整個視窗全螢幕。
    注意：pywebview 會掃描 js_api 物件的公開屬性，所以內部狀態一律用底線開頭。
    """

    def __init__(self):
        self._window = None
        self._fullscreen = False

    def set_fullscreen(self, on):
        on = bool(on)
        if self._window is not None and on != self._fullscreen:
            self._window.toggle_fullscreen()
            self._fullscreen = on


def _error_window(webview, message: str) -> int:
    import html

    body = (
        "<body style='font:15px system-ui,\"Microsoft JhengHei\",sans-serif;padding:28px'>"
        f"<h2>{WINDOW_TITLE} / TubeTran</h2><p style='white-space:pre-wrap'>{html.escape(message)}</p></body>"
    )
    webview.create_window(WINDOW_TITLE, html=body, width=680, height=340)
    webview.start()
    return 1


def _set_app_user_model_id() -> None:
    """讓 Windows 把這個程式當成獨立的應用程式，而不是歸在 python.exe 底下，
    工作列才會顯示我們自己的圖示（開發模式尤其需要）。"""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("io.github.codemee.tubetran")
        except (OSError, AttributeError):
            pass


def run_desktop() -> int:
    try:
        import webview
    except ImportError:
        print("桌面模式需要 pywebview。安裝時加上 desktop 額外套件：\n"
              "  uv tool install \"tubetran[desktop]\"（從原始碼資料夾則是 uv tool install \".[desktop]\"）\n"
              "  或在專案內 uv sync --extra desktop\n"
              "只想用瀏覽器的話可改用：tubetran --server", file=sys.stderr)
        return 1
    _set_app_user_model_id()

    # 沒有 API 金鑰也照常開啟：網頁會自動打開設定面板請使用者輸入
    port = _pick_port()
    backend = _BackgroundServer(port)
    if not backend.start():
        return _error_window(webview, f"後端啟動失敗，詳細原因請看記錄檔：\n{config.DATA_DIR / 'tubetran.log'}")
    try:
        api = _DesktopApi()
        api._window = webview.create_window(
            WINDOW_TITLE, f"http://127.0.0.1:{port}/", width=1280, height=860,
            min_size=(900, 600), js_api=api,
        )
        # private_mode=False + storage_path：保留 localStorage（主題、語言設定）與 cookie
        # icon：視窗標題列／工作列的圖示。沒指定時 Windows 會用 python.exe 的圖示（開發模式）
        webview.start(
            private_mode=False,
            storage_path=str(config.DATA_DIR / "webview"),
            icon=str(config.STATIC_DIR / "logo" / "tubetran.ico"),
        )
    finally:
        backend.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    argv = sys.argv[1:] if argv is None else argv
    _setup_streams(cli_use=bool(argv))
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    if args.server:
        return run_server(args.host, args.port)
    return run_desktop()
