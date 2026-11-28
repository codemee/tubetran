"""桌面模式（Windows）的視窗控制。

無框視窗沒有系統標題列與邊框，pywebview 也不提供最大化與邊緣縮放，所以這裡自己處理：
- 最大化：把視窗鋪滿「工作區」（不蓋住工作列），還原時回到原本的位置與大小。
- 邊緣縮放：網頁在視窗邊緣放透明的把手，拖曳時由頁面回報位移，這裡算出新的視窗範圍。

座標一律是實體像素（x, y, 寬, 高）。縮放的計算是純函式，不依賴 Windows，可以單元測試。
"""
import ctypes
import sys
from ctypes import wintypes

Rect = tuple[int, int, int, int]  # x, y, w, h
EDGES = ("n", "s", "e", "w", "ne", "nw", "se", "sw")
MAX_DELTA = 50_000  # 頁面回報的位移上限（實體像素），擋掉不合理的數值


def resized_rect(rect: Rect, edge: str, dx: int, dy: int, min_w: int, min_h: int) -> Rect:
    """從 rect 拖曳 edge 邊（或角）位移 (dx, dy) 之後的新範圍；寬高不會小於最小值，
    拖曳左／上邊時，另一側（右／下邊）保持不動。"""
    if edge not in EDGES:
        raise ValueError(f"不合法的邊緣：{edge!r}")
    dx = max(-MAX_DELTA, min(MAX_DELTA, int(dx)))
    dy = max(-MAX_DELTA, min(MAX_DELTA, int(dy)))
    x, y, w, h = rect
    if "e" in edge:
        w = max(min_w, w + dx)
    if "s" in edge:
        h = max(min_h, h + dy)
    if "w" in edge:
        nw = max(min_w, w - dx)
        x, w = x + (w - nw), nw
    if "n" in edge:
        nh = max(min_h, h - dy)
        y, h = y + (h - nh), nh
    return x, y, w, h


LTRB = tuple[int, int, int, int]  # left, top, right, bottom


def client_rect_for_zoomed(proposed: LTRB, monitor: LTRB, work: LTRB, zoomed: bool) -> LTRB:
    """WM_NCCALCSIZE 時，視窗的客戶區（= 我們畫的內容）該是哪一塊。

    我們替無框視窗加上了可調整大小的邊框樣式（WS_THICKFRAME），但不要畫出邊框，所以客戶區就是整個視窗。
    唯一的例外是系統把視窗「最大化」（Win+↑、FancyZones 的最大化等）：Windows 會讓視窗往螢幕外多出一圈邊框
    （厚度依 DPI 而異），客戶區要限制在工作區裡，否則內容會被切掉。直接取與工作區的交集，不必猜邊框厚度。
    全螢幕（範圍剛好等於整個螢幕，含工作列區域）不用處理。"""
    if not zoomed or proposed == monitor:
        return proposed
    left, top, right, bottom = proposed
    return max(left, work[0]), max(top, work[1]), min(right, work[2]), min(bottom, work[3])


def client_rect_with_native_frame(proposed: LTRB, default_client: LTRB, monitor: LTRB, work: LTRB, zoomed: bool) -> LTRB:
    """保留原生邊框的版本（Windows 11 的貼齊版面需要）：左、右、下用系統算出的客戶區（default_client），
    只有上緣收回到視窗最上面——標題列的位置交給網頁畫。最大化與全螢幕的處理和 client_rect_for_zoomed 一樣。"""
    if zoomed or proposed == monitor:
        return client_rect_for_zoomed(proposed, monitor, work, zoomed)
    return default_client[0], proposed[1], default_client[2], default_client[3]


def snap_layouts_supported() -> bool:
    """Windows 11（組建 22000 以上）才有貼齊版面選單。"""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


def same_rect(a: Rect, b: Rect, tol: int = 2) -> bool:
    """兩個範圍是否相同（容許幾個像素的誤差）。"""
    return all(abs(p - q) <= tol for p, q in zip(a, b))


# ── Win32（只在 Windows 上使用）──
_SWP_NOZORDER, _SWP_NOACTIVATE = 0x0004, 0x0010
_MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_user32_dll = None


def _user32():
    """本模組專用的 user32。

    不能用 ctypes.windll.user32：它是整個程序共用的物件，在上面設定 argtypes 會影響 pywebview 自己的
    呼叫（例如它移動視窗時對 SetWindowPos 的 cx、cy 傳 None），造成「縮放或最大化過之後就無法拖曳視窗」。
    ctypes.WinDLL(...) 每次建立的是獨立的實例，有各自的函式快取，設定 argtypes 不會外溢。"""
    global _user32_dll
    if sys.platform != "win32":
        raise OSError("只支援 Windows")
    if _user32_dll is not None:
        return _user32_dll
    u = ctypes.WinDLL("user32")
    # 明確指定型別：HWND 在 64 位元上是 64 位元，用預設的 int 會被截斷
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.MonitorFromWindow.restype = wintypes.HANDLE
    u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.FindWindowW.restype = wintypes.HWND
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u.SetWindowLongW.restype = ctypes.c_long
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.CallWindowProcW.restype = ctypes.c_ssize_t
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(_POINT)]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetDC.argtypes = [wintypes.HWND]
    u.GetDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.NotifyWinEvent.argtypes = [wintypes.DWORD, wintypes.HWND, ctypes.c_long, ctypes.c_long]
    u.NotifyWinEvent.restype = None
    _user32_dll = u
    return u


def find_window(title: str) -> int | None:
    return _user32().FindWindowW(None, title) or None


def foreground_window() -> int:
    """目前在最前面（接收鍵盤輸入）的視窗；沒有就是 0。"""
    return int(_user32().GetForegroundWindow() or 0)


def key_down(vk: int) -> bool:
    """某個按鍵（虛擬鍵碼）目前是否被按住。"""
    return bool(_user32().GetAsyncKeyState(vk) & 0x8000)


def cursor_pos() -> tuple[int, int]:
    """滑鼠游標在螢幕上的位置（實體像素）。網頁收不到 YouTube iframe 內的滑鼠事件，
    所以桌面版靠它判斷「滑鼠有沒有在動」，才能像 YouTube 控制列一樣在不動約 2.5 秒後隱藏全螢幕鈕。"""
    p = _POINT()
    if not _user32().GetCursorPos(ctypes.byref(p)):
        raise OSError("GetCursorPos 失敗")
    return p.x, p.y


WHITE_MIN = 238  # 一個像素的 R、G、B 都不小於這個值，就算「白」


def white_fraction(bgra: bytes, width: int, height: int, step: int = 2) -> float:
    """32 位元 BGRA 像素資料中，「白」像素的比例（每隔 step 個像素取樣，省時間）。純函式，可單元測試。"""
    if width <= 0 or height <= 0 or len(bgra) < width * height * 4:
        return 0.0
    white = total = 0
    for y in range(0, height, step):
        row = y * width * 4
        for x in range(0, width, step):
            i = row + x * 4
            total += 1
            if bgra[i] >= WHITE_MIN and bgra[i + 1] >= WHITE_MIN and bgra[i + 2] >= WHITE_MIN:
                white += 1
    return white / total if total else 0.0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_gdi32_dll = None


def _gdi32():
    global _gdi32_dll
    if _gdi32_dll is None:
        g = ctypes.WinDLL("gdi32")  # 專屬實例，理由同 _user32：不改動程序共用的 ctypes.windll.gdi32
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC,
                             ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteDC.argtypes = [wintypes.HDC]
        _gdi32_dll = g
    return _gdi32_dll


def screen_white_fraction(x: int, y: int, w: int, h: int, step: int = 2) -> float:
    """從螢幕截取 (x, y, w, h)（實體像素）這一小塊，回傳「白」像素的比例。只回傳一個數字，不保存也不回傳畫面內容。"""
    u, g = _user32(), _gdi32()
    hdc = u.GetDC(None)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        g.BitBlt(mdc, 0, 0, w, h, hdc, x, y, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT（連分層視窗、WebView2 的內容也截得到）
        bi = _BITMAPINFOHEADER()
        bi.biSize, bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = ctypes.sizeof(bi), w, -h, 1, 32
        buf = (ctypes.c_ubyte * (w * h * 4))()
        g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        return white_fraction(bytes(buf), w, h, step)
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(None, hdc)


def client_origin(hwnd: int) -> tuple[int, int]:
    """視窗客戶區左上角在螢幕上的位置（實體像素）。"""
    p = _POINT()
    _user32().ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


def is_iconic(hwnd: int) -> bool:
    return bool(_user32().IsIconic(hwnd))


def get_rect(hwnd: int) -> Rect:
    r = _RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def set_rect(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    _user32().SetWindowPos(hwnd, None, x, y, w, h, _SWP_NOZORDER | _SWP_NOACTIVATE)


def work_area(hwnd: int) -> Rect:
    """視窗目前所在螢幕的工作區（扣掉工作列）。"""
    u = _user32()
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right - r.left, r.bottom - r.top


# ── 讓視窗「可以被調整大小」：WS_THICKFRAME，但不畫出邊框 ──
# 視窗管理程式（PowerToys FancyZones 等）靠 WS_THICKFRAME（又叫 WS_SIZEBOX）判斷視窗能不能縮放；
# 沒有的話它只會移動位置、沿用原本的寬高（FancyZones 原始碼 AdjustRectForSizeWindowToRect）。
# 所以無框視窗也要有這個樣式，再攔截 WM_NCCALCSIZE 讓客戶區涵蓋整個視窗，邊框就不會被畫出來。
_WS_THICKFRAME, _WS_MINIMIZEBOX = 0x00040000, 0x00020000
_GWL_STYLE, _GWLP_WNDPROC = -16, -4
_WM_NCCALCSIZE = 0x0083
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0020


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", _RECT * 3), ("lppos", ctypes.c_void_p)]


# WINFUNCTYPE 只存在於 Windows 的 ctypes；其他平台用不到這個型別，退而用 CFUNCTYPE 讓模組仍可匯入
_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_WNDPROC = _FUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_hooks: dict[int, tuple] = {}  # hwnd -> (回呼物件, 原本的視窗程序)；回呼物件必須一直存活，否則會被回收而當機


def _monitor_rects(hwnd: int) -> tuple[LTRB, LTRB]:
    u = _user32()
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    m, w = info.rcMonitor, info.rcWork
    return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)


def is_zoomed(hwnd: int) -> bool:
    """視窗是否被系統「最大化」（Win+↑、拖到螢幕上緣、FancyZones 等；不含我們自己鋪滿工作區的最大化）。"""
    return bool(_user32().IsZoomed(hwnd))


def restore(hwnd: int) -> None:
    _user32().ShowWindow(hwnd, 9)  # SW_RESTORE


def maximize(hwnd: int) -> None:
    _user32().ShowWindow(hwnd, 3)  # SW_MAXIMIZE


def notify_move_size(hwnd: int, start: bool) -> None:
    """廣播「視窗開始／結束被使用者移動」（EVENT_SYSTEM_MOVESIZESTART / END）。

    FancyZones 這類視窗管理程式是靠這兩個系統事件得知有視窗正在被拖曳，並在結束時把視窗吸進區域
    （Shift 拖曳吸附）。我們的視窗是由頁面程式碼一步步搬動的（交給系統的原生移動流程對 WebView2 這種跨行程輸入
    行不通，已實測），系統不會自己發出這兩個事件，所以由我們在拖曳開始與結束時自己廣播。
    視窗位置改變的事件（EVENT_OBJECT_LOCATIONCHANGE）是系統在每次搬動時自動發出的，不用管。"""
    _user32().NotifyWinEvent(0x000A if start else 0x000B, hwnd, -4, 0)  # OBJID_WINDOW = -4, CHILDID_SELF = 0


def has_resizable_frame(hwnd: int) -> bool:
    return bool(_user32().GetWindowLongW(hwnd, _GWL_STYLE) & _WS_THICKFRAME)


def install_resizable_frame(hwnd: int, keep_native_frame: bool = False) -> bool:
    """替視窗加上 WS_THICKFRAME 與最小化鈕樣式，並攔截 WM_NCCALCSIZE。可重複呼叫。
    keep_native_frame=False：客戶區涵蓋整個視窗，邊框不會被畫出來。
    keep_native_frame=True：保留系統的左、右、下邊框、只收回標題列（Windows 11 的貼齊版面選單需要視窗有原生邊框，
    見 docs/zh-TW/windows-snap-layouts.md）。
    回傳視窗現在是否具有 WS_THICKFRAME。"""
    u = _user32()
    fresh = hwnd not in _hooks
    if fresh:
        old = u.GetWindowLongPtrW(hwnd, _GWLP_WNDPROC)

        def proc(h, msg, wparam, lparam):
            try:
                if msg == _WM_NCCALCSIZE and wparam:
                    params = ctypes.cast(lparam, ctypes.POINTER(_NCCALCSIZE_PARAMS)).contents
                    r = params.rgrc[0]
                    proposed = (r.left, r.top, r.right, r.bottom)
                    monitor, work = _monitor_rects(h)
                    zoomed = bool(u.IsZoomed(h))
                    if _hooks[h][2]:
                        default = proposed
                        if not zoomed and proposed != monitor:
                            u.CallWindowProcW(old, h, msg, wparam, lparam)  # 先讓系統算出原生邊框
                            default = (r.left, r.top, r.right, r.bottom)
                        new = client_rect_with_native_frame(proposed, default, monitor, work, zoomed)
                    else:
                        new = client_rect_for_zoomed(proposed, monitor, work, zoomed)
                    r.left, r.top, r.right, r.bottom = new
                    return 0
            except Exception:  # noqa: BLE001 — 視窗程序裡不能丟例外；出錯就交還給原本的處理
                pass
            return u.CallWindowProcW(old, h, msg, wparam, lparam)

        callback = _WNDPROC(proc)
        _hooks[hwnd] = (callback, old, keep_native_frame)
        u.SetWindowLongPtrW(hwnd, _GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p).value)
    else:
        _hooks[hwnd] = (*_hooks[hwnd][:2], keep_native_frame)
    style = u.GetWindowLongW(hwnd, _GWL_STYLE)
    if fresh or style & (_WS_THICKFRAME | _WS_MINIMIZEBOX) != (_WS_THICKFRAME | _WS_MINIMIZEBOX):
        u.SetWindowLongW(hwnd, _GWL_STYLE, style | _WS_THICKFRAME | _WS_MINIMIZEBOX)
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)
    return has_resizable_frame(hwnd)


# ── 最大化鈕上的「貼齊版面」：覆蓋在按鈕上的透明子視窗 ──
# Windows 11 只有在滑鼠停在「WM_NCHITTEST 回報 HTMAXBUTTON」的地方才會顯示貼齊版面選單。
# 但 WebView2 的內容是另一個行程的子視窗（Chrome_WidgetWin_1），滑鼠在它上面時，系統只會問它、
# 不會去問我們的頂層視窗，所以頂層視窗的 WM_NCHITTEST 根本收不到。解法（Tauri 的 decorum 也這樣做）：
# 在最大化鈕的位置蓋一個同行程的透明子視窗，由它回報 HTMAXBUTTON，並自己處理懸停、按下與點擊。
_WM_NCHITTEST, _WM_NCMOUSEMOVE, _WM_NCMOUSELEAVE = 0x0084, 0x00A0, 0x02A2
_WM_NCLBUTTONDOWN, _WM_NCLBUTTONUP, _WM_MOUSEMOVE = 0x00A1, 0x00A2, 0x0200
_WM_TIMER, _WM_ERASEBKGND, _WM_SYSCOMMAND, _WM_NCDESTROY = 0x0113, 0x0014, 0x0112, 0x0082
_HTMAXBUTTON, _SC_MAXIMIZE, _SC_RESTORE = 9, 0xF030, 0xF120
_WS_CHILD, _WS_CLIPSIBLINGS = 0x40000000, 0x04000000
_WS_EX_LAYERED, _WS_EX_NOACTIVATE = 0x00080000, 0x08000000
_SWP_SHOWWINDOW, _SWP_HIDEWINDOW = 0x0040, 0x0080
_TME_LEAVE, _TME_NONCLIENT = 0x2, 0x10
_HWND_TOP = 0
_HOVER_TIMER, _HOVER_POLL_MS = 1, 60
BTN_IDLE, BTN_HOVER, BTN_PRESSED = 0, 1, 2
_OVERLAY_CLASS = "TubeTranMaxButton"


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


_overlay_ready = False
_overlays: dict[int, "_MaxButtonOverlay"] = {}          # 父視窗 hwnd -> 覆蓋層
_overlays_by_hwnd: dict[int, "_MaxButtonOverlay"] = {}  # 覆蓋層自己的 hwnd -> 覆蓋層
_overlay_class: tuple | None = None                     # (視窗程序回呼, hInstance)：類別只註冊一次，回呼要一直存活


def _overlay_proc(h, msg, wparam, lparam):
    ov = _overlays_by_hwnd.get(h)
    if ov is None:  # 建立視窗的過程中（WM_NCCREATE 等）還沒登記
        return _user32().DefWindowProcW(h, msg, wparam, lparam)
    return ov.wndproc(h, msg, wparam, lparam)


def _register_overlay_class():
    global _overlay_class
    if _overlay_class is None:
        u = _overlay_api()
        k32 = ctypes.WinDLL("kernel32")
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        hinst = k32.GetModuleHandleW(None)
        callback = _WNDPROC(_overlay_proc)
        wc = _WNDCLASSEXW()
        wc.cbSize, wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = ctypes.sizeof(wc), callback, hinst, _OVERLAY_CLASS
        if not u.RegisterClassExW(ctypes.byref(wc)):
            raise OSError("無法註冊最大化鈕覆蓋層的視窗類別")
        _overlay_class = (callback, hinst)
    return _overlay_class[1]


def _overlay_api():
    """覆蓋層專用的 user32 函式簽章（專屬的 WinDLL 實例，理由同 _user32）。"""
    global _overlay_ready
    u = _user32()
    if not _overlay_ready:
        u.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
        u.RegisterClassExW.restype = wintypes.ATOM
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
        u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        u.SetTimer.restype = ctypes.c_size_t
        u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        u.TrackMouseEvent.argtypes = [ctypes.POINTER(_TRACKMOUSEEVENT)]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        _overlay_ready = True
    return u


class _MaxButtonOverlay:
    """蓋在自製最大化鈕上的透明子視窗。必須在建立父視窗的執行緒（UI 執行緒）上建立，它的訊息才會被那邊處理。
    on_state(state) 在 UI 執行緒被呼叫（BTN_IDLE／BTN_HOVER／BTN_PRESSED）；回呼要很快，不能等網頁。"""

    def __init__(self, parent: int, on_state):
        self.parent, self._on_state, self.state = parent, on_state, BTN_IDLE
        u = _overlay_api()
        hinst = _register_overlay_class()
        self.hwnd = u.CreateWindowExW(_WS_EX_LAYERED | _WS_EX_NOACTIVATE, _OVERLAY_CLASS, None, _WS_CHILD | _WS_CLIPSIBLINGS,
                                      0, 0, 1, 1, parent, None, hinst, None)
        if not self.hwnd:
            raise OSError("無法建立最大化鈕覆蓋層")
        _overlays_by_hwnd[self.hwnd] = self
        u.SetLayeredWindowAttributes(self.hwnd, 0, 1, 0x2)  # LWA_ALPHA：幾乎全透明，但仍然擋得住滑鼠、也能被命中測試

    def _set_state(self, state: int) -> None:
        previous, self.state = self.state, state
        if state == previous:
            return
        u = _user32()
        if state == BTN_IDLE:
            u.KillTimer(self.hwnd, _HOVER_TIMER)
        elif previous == BTN_IDLE:
            u.SetTimer(self.hwnd, _HOVER_TIMER, _HOVER_POLL_MS, None)  # 滑鼠離開的訊息不一定可靠，另外定時確認游標還在不在
        try:
            self._on_state(state)
        except Exception:  # noqa: BLE001
            pass

    def _cursor_inside(self) -> bool:
        x, y = cursor_pos()
        r = get_rect(self.hwnd)
        return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]

    def wndproc(self, h, msg, wparam, lparam):
        u = _user32()
        try:
            if msg == _WM_NCHITTEST:
                return _HTMAXBUTTON
            if msg == _WM_ERASEBKGND:
                return 1
            if msg == _WM_NCMOUSEMOVE:
                if self.state == BTN_IDLE:
                    self._set_state(BTN_HOVER)
                    u.TrackMouseEvent(ctypes.byref(_TRACKMOUSEEVENT(ctypes.sizeof(_TRACKMOUSEEVENT), _TME_LEAVE | _TME_NONCLIENT, h, 0)))
                return u.DefWindowProcW(h, msg, wparam, lparam)  # 照常交還系統：貼齊版面靠這個訊息觸發
            if msg == _WM_MOUSEMOVE:
                self._set_state(BTN_IDLE)
            elif msg == _WM_NCMOUSELEAVE:
                # 貼齊版面選單一出現就會送來這個訊息，但游標其實還在鈕上，按鈕要維持高亮（原生視窗也是）。
                # 是不是真的離開，由定時器依游標位置判斷。
                if not self._cursor_inside():
                    self._set_state(BTN_IDLE)
            elif msg == _WM_TIMER and wparam == _HOVER_TIMER:
                if not self._cursor_inside():
                    self._set_state(BTN_IDLE)
                return 0
            elif msg == _WM_NCLBUTTONDOWN:
                self._set_state(BTN_PRESSED)
                return 0  # 不交給系統：它會去畫不存在的標題列按鈕
            elif msg == _WM_NCLBUTTONUP:
                pressed = self.state == BTN_PRESSED
                self._set_state(BTN_HOVER)
                if pressed:
                    u.PostMessageW(self.parent, _WM_SYSCOMMAND, _SC_RESTORE if u.IsZoomed(self.parent) else _SC_MAXIMIZE, 0)
                return 0
        except Exception:  # noqa: BLE001 — 視窗程序裡不能丟例外
            pass
        return u.DefWindowProcW(h, msg, wparam, lparam)

    def place(self, rect: Rect | None) -> None:
        """rect = 最大化鈕在父視窗客戶區裡的位置（實體像素）；None 表示藏起來（全螢幕、按鈕不見時）。"""
        u = _user32()
        if rect is None:
            u.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_HIDEWINDOW)
            self._set_state(BTN_IDLE)
            return
        x, y, w, h = rect
        u.SetWindowPos(self.hwnd, _HWND_TOP, x, y, w, h, _SWP_NOACTIVATE | _SWP_SHOWWINDOW)  # 每次都放到最上面，蓋過 WebView2



def place_max_button_overlay(parent: int, rect: Rect | None, on_state) -> None:
    """建立（第一次）並擺放最大化鈕的覆蓋層。必須在 UI 執行緒呼叫。"""
    ov = _overlays.get(parent)
    if ov is None:
        if rect is None:
            return
        ov = _overlays[parent] = _MaxButtonOverlay(parent, on_state)
    ov.place(rect)
