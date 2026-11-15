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
from pathlib import Path

from tubetran import config, winctl

WINDOW_TITLE = "水管譯工"
# 視窗的最小尺寸（邏輯像素）。要夠小：視窗管理程式（平鋪／貼齊）會直接指定位置與大小，
# 比最小值小的要求會被擋住，結果是「位置對了、大小沒變」。窄到這個程度版面仍可用（頂欄換成兩列、內容單欄）。
# 寬度 400：頂欄第一列要放得下圖示＋設定／語言／主題鈕＋視窗按鈕（約 362px），再窄就會換行、按鈕重疊。
MIN_WINDOW_SIZE = (400, 240)


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
    p.add_argument("--native-titlebar", action="store_true",
                   help="桌面模式使用系統標題列（預設在 Windows 上是無框視窗加自製視窗按鈕）")
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
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    # 視窗程式（打包後的 exe）沒有主控台時看不到輸出（例如 CI）；環境變數指定檔案時，同時寫一份到那裡
    target = os.environ.get("TUBETRAN_SELFTEST_OUT")
    if target:
        Path(target).write_text(text, encoding="utf-8")
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

    def __init__(self, custom_chrome: bool = False):
        self._window = None
        self._fullscreen = False
        # custom_chrome：視窗沒有系統標題列與邊框，由網頁自己畫視窗按鈕、處理拖曳與邊緣縮放
        self._custom = custom_chrome
        self._maximized = False
        self._normal_rect = None
        self._resize = None
        self._moving = False

    def set_fullscreen(self, on):
        on = bool(on)
        if self._window is not None and on != self._fullscreen:
            self._window.toggle_fullscreen()
            self._fullscreen = on
            self._apply_resizable_frame()  # WinForms 重設邊框樣式時可能把我們加的 WS_THICKFRAME 洗掉

    def _apply_resizable_frame(self):
        """讓無框視窗仍具有 WS_THICKFRAME（但不畫出邊框）。視窗管理程式（FancyZones 等）靠它判斷
        視窗能不能縮放；沒有的話只會移動位置、不改大小。"""
        if not self._custom or self._window is None:
            return
        try:
            hwnd = self._hwnd()
            if hwnd:
                winctl.install_resizable_frame(hwnd)
        except Exception as e:  # noqa: BLE001 — 失敗只是少了「被排版程式縮放」的功能，不能讓程式掛掉
            print(f"無法設定視窗的可調整大小樣式：{e}", file=sys.stderr)

    def _on_shown(self):
        self._apply_resizable_frame()

    # ── 自製視窗按鈕（只有無框視窗才會用到）──
    def _hwnd(self):
        try:
            return int(self._window.native.Handle.ToInt64())
        except Exception:  # noqa: BLE001 — 取不到就用標題找
            return winctl.find_window(WINDOW_TITLE)

    def _sync_maximized(self):
        """「最大化」有兩種：我們自己鋪滿工作區（記在旗標裡），以及系統的最大化（Win+↑、拖到螢幕上緣貼齊、
        FancyZones 等，用 IsZoomed 查）。視窗若被外部改過範圍，旗標要放掉，否則按鈕會停在「還原」、縮放也被擋住。"""
        if not self._custom:
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        if winctl.is_zoomed(hwnd):
            self._maximized = True
        elif self._maximized and not winctl.same_rect(winctl.get_rect(hwnd), winctl.work_area(hwnd)):
            self._maximized = False

    def window_state(self):
        self._sync_maximized()
        return {"custom": self._custom, "maximized": self._maximized}

    def window_minimize(self):
        if self._custom and self._window is not None:
            self._window.minimize()

    def window_toggle_maximize(self):
        """最大化／還原。最大化是鋪滿螢幕「工作區」（不蓋住工作列），由我們自己記住原本的範圍。"""
        self._sync_maximized()
        hwnd = self._hwnd() if self._custom else None
        if hwnd:
            if winctl.is_zoomed(hwnd):  # 系統最大化：用系統的還原（回到最大化之前的位置與大小）
                winctl.restore(hwnd)
                self._maximized = False
            elif self._maximized:
                if self._normal_rect:
                    winctl.set_rect(hwnd, *self._normal_rect)
                self._maximized = False
            else:
                self._normal_rect = winctl.get_rect(hwnd)
                winctl.set_rect(hwnd, *winctl.work_area(hwnd))
                self._maximized = True
        return self.window_state()

    def window_move_begin(self):
        """頁首拖曳（由 pywebview 在頁面裡一步步搬動視窗）開始：廣播「視窗開始被移動」。
        FancyZones 靠這個事件才會顯示區域、在放開時把視窗吸進去（Shift 拖曳）。"""
        hwnd = self._hwnd() if self._custom and not self._maximized and not self._fullscreen else None
        if hwnd and not self._moving:
            self._moving = True
            winctl.notify_move_size(hwnd, True)

    def window_move_end(self):
        """拖曳結束：廣播「視窗結束被移動」，FancyZones 此時才會把視窗吸進區域並套用區域的大小。"""
        if self._moving:
            self._moving = False
            hwnd = self._hwnd()
            if hwnd:
                winctl.notify_move_size(hwnd, False)

    def window_close(self):
        if self._window is not None:
            self._window.destroy()

    # ── 邊緣縮放：頁面在 pointerdown 時 begin，移動時回報位移（實體像素），放開時 end ──
    def resize_begin(self, edge, dpr=1.0):
        self._sync_maximized()
        hwnd = self._hwnd() if self._custom and not self._maximized else None
        if hwnd and edge in winctl.EDGES:
            self._resize = {"hwnd": hwnd, "rect": winctl.get_rect(hwnd), "dpr": max(0.5, min(float(dpr), 8.0)), "seq": 0}

    def resize_to(self, edge, dx, dy, seq):
        rs = self._resize
        if not rs or edge not in winctl.EDGES or int(seq) <= rs["seq"]:  # 橋接的呼叫可能亂序，舊的直接丟掉
            return
        rs["seq"] = int(seq)
        min_w, min_h = (int(v * rs["dpr"]) for v in MIN_WINDOW_SIZE)
        winctl.set_rect(rs["hwnd"], *winctl.resized_rect(rs["rect"], edge, dx, dy, min_w, min_h))

    def resize_end(self):
        self._resize = None


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


def _enable_per_monitor_dpi(user32=None, shcore=None) -> bool:
    """宣告成「每螢幕 DPI 感知（PerMonitorV2）」，必須在建立任何視窗之前呼叫。

    pywebview 啟動時只會宣告成「系統 DPI 感知」（SetProcessDPIAware，只認主螢幕的縮放）。多螢幕、縮放比例不同
    （例如 100%／125%／200%）時，系統會替這種視窗再做一次縮放，而每螢幕感知的視窗管理程式（PowerToys、
    mvapp 等）是用實體像素指定位置與大小，兩邊疊加就算錯：位置對、大小不對。
    先宣告成每螢幕感知，pywebview 之後的 SetProcessDPIAware 呼叫就會被忽略，視窗的位置與大小都是實體像素。
    回傳是否設定成功（已經被設定過、或系統太舊，都回 False，不影響執行）。"""
    if sys.platform != "win32" and user32 is None:
        return False
    try:
        user32 = user32 or ctypes.windll.user32
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return True
        shcore = shcore or ctypes.windll.shcore
        return shcore.SetProcessDpiAwareness(2) == 0                    # PROCESS_PER_MONITOR_DPI_AWARE（Windows 8.1）
    except (OSError, AttributeError):
        return False


def run_desktop(native_titlebar: bool = False) -> int:
    try:
        import webview
    except ImportError:
        print("桌面模式需要 pywebview。安裝時加上 desktop 額外套件：\n"
              "  uv tool install \"tubetran[desktop]\"（從原始碼資料夾則是 uv tool install \".[desktop]\"）\n"
              "  或在專案內 uv sync --extra desktop\n"
              "只想用瀏覽器的話可改用：tubetran --server", file=sys.stderr)
        return 1
    _enable_per_monitor_dpi()
    _set_app_user_model_id()

    # 沒有 API 金鑰也照常開啟：網頁會自動打開設定面板請使用者輸入
    port = _pick_port()
    backend = _BackgroundServer(port)
    if not backend.start():
        return _error_window(webview, f"後端啟動失敗，詳細原因請看記錄檔：\n{config.DATA_DIR / 'tubetran.log'}")
    try:
        # 無框視窗（自製標題列與視窗按鈕）目前只在 Windows 上做並測試過；其他系統維持系統標題列
        custom = sys.platform == "win32" and not native_titlebar
        api = _DesktopApi(custom_chrome=custom)
        # easy_drag=False：預設的「頁面任何地方按住都能拖動視窗」會吃掉選取文字、拖曳進度條等操作，
        # 改成只有 .pywebview-drag-region（頁首的空白處）能拖；DIRECT_TARGET_ONLY 讓裡面的輸入框與按鈕不觸發拖曳
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
        api._window = webview.create_window(
            WINDOW_TITLE, f"http://127.0.0.1:{port}/", width=1280, height=860,
            min_size=MIN_WINDOW_SIZE, js_api=api, frameless=custom, easy_drag=False,
        )
        api._window.events.shown += api._on_shown
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
    return run_desktop(native_titlebar=args.native_titlebar)
