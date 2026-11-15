import sys
from pathlib import Path

import pytest

from tubetran import cli, config, winctl

R = (100, 200, 1000, 700)  # x, y, w, h
MIN = (900, 600)


@pytest.mark.parametrize("edge,dx,dy,expected", [
    ("e", 50, 999, (100, 200, 1050, 700)),     # 右邊：只動寬
    ("s", 999, 40, (100, 200, 1000, 740)),     # 下邊：只動高
    ("se", 30, 20, (100, 200, 1030, 720)),
    ("w", -40, 0, (60, 200, 1040, 700)),       # 左邊往外拉：x 跟著動，右邊緣不動
    ("n", 0, -30, (100, 170, 1000, 730)),      # 上邊往外拉：y 跟著動，下邊緣不動
    ("nw", -10, -20, (90, 180, 1010, 720)),
    ("ne", 10, -20, (100, 180, 1010, 720)),
    ("sw", -10, 20, (90, 200, 1010, 720)),
])
def test_resized_rect_edges(edge, dx, dy, expected):
    assert winctl.resized_rect(R, edge, dx, dy, *MIN) == expected


def test_resized_rect_respects_minimum_and_keeps_opposite_edge_fixed():
    # 把右邊往左拉到比最小寬度還小：寬度停在最小值
    assert winctl.resized_rect(R, "e", -500, 0, *MIN)[2] == 900
    # 把左邊往右拉過頭：寬度停在最小值，而且右邊緣（x + w）不動
    x, y, w, h = winctl.resized_rect(R, "w", 500, 0, *MIN)
    assert w == 900 and x + w == R[0] + R[2]
    # 上邊同理
    x, y, w, h = winctl.resized_rect(R, "n", 0, 500, *MIN)
    assert h == 600 and y + h == R[1] + R[3]


def test_resized_rect_rejects_bad_input():
    with pytest.raises(ValueError):
        winctl.resized_rect(R, "x", 1, 1, *MIN)
    assert winctl.resized_rect(R, "e", 10**9, 0, *MIN)[2] == 1000 + winctl.MAX_DELTA  # 位移有上限


class _FakeWindow:
    def __init__(self):
        self.calls = []

    def minimize(self):
        self.calls.append("minimize")

    def destroy(self):
        self.calls.append("destroy")

    def toggle_fullscreen(self):
        self.calls.append("fullscreen")


@pytest.fixture
def api(monkeypatch):
    """假的視窗與假的 Win32：記錄 set_rect 的呼叫，不碰真正的視窗。"""
    state = {"rect": (100, 200, 1000, 700), "set": []}
    monkeypatch.setattr(winctl, "get_rect", lambda hwnd: state["rect"])
    monkeypatch.setattr(winctl, "work_area", lambda hwnd: (0, 0, 1920, 1040))

    def set_rect(hwnd, x, y, w, h):
        state["rect"] = (x, y, w, h)
        state["set"].append((x, y, w, h))

    monkeypatch.setattr(winctl, "set_rect", set_rect)
    a = cli._DesktopApi(custom_chrome=True)
    a._window = _FakeWindow()
    a._hwnd = lambda: 1234
    a.state = state
    return a


def test_maximize_fills_work_area_and_restore_goes_back(api):
    assert api.window_state() == {"custom": True, "maximized": False}
    assert api.window_toggle_maximize()["maximized"] is True
    assert api.state["rect"] == (0, 0, 1920, 1040)           # 工作區：不蓋住工作列
    assert api.window_toggle_maximize()["maximized"] is False
    assert api.state["rect"] == (100, 200, 1000, 700)         # 回到原本的位置與大小


def test_drag_broadcasts_move_size_events_once_so_window_managers_can_snap(api, monkeypatch):
    """FancyZones 靠 EVENT_SYSTEM_MOVESIZESTART/END 得知視窗正在被拖曳（Shift 拖曳吸附）。
    我們的視窗由頁面一步步搬動，系統不會自己發這兩個事件，要由我們廣播；而且成對、不重複。"""
    sent = []
    monkeypatch.setattr(winctl, "notify_move_size", lambda hwnd, start: sent.append((hwnd, start)))
    api.window_move_end()                       # 沒有開始過就結束：不能亂發
    assert sent == []
    api.window_move_begin(); api.window_move_begin()
    assert sent == [(1234, True)]               # 重複呼叫只發一次
    api.window_move_end(); api.window_move_end()
    assert sent == [(1234, True), (1234, False)]


def test_no_move_events_while_maximized_or_fullscreen_or_native_titlebar(api, monkeypatch):
    sent = []
    monkeypatch.setattr(winctl, "notify_move_size", lambda hwnd, start: sent.append(start))
    api.window_toggle_maximize()                # 最大化時不能拖曳移動
    api.window_move_begin()
    api._maximized = False
    api._fullscreen = True                      # 全螢幕時也不發
    api.window_move_begin()
    native = cli._DesktopApi(custom_chrome=False)
    native._window = _FakeWindow(); native._hwnd = lambda: 1
    native.window_move_begin()                  # 使用系統標題列：系統自己會發，我們不重複
    assert sent == []


def test_minimize_and_close_delegate_to_window(api):
    api.window_minimize()
    api.window_close()
    assert api._window.calls == ["minimize", "destroy"]


def test_native_titlebar_mode_does_not_touch_the_window(monkeypatch):
    a = cli._DesktopApi(custom_chrome=False)
    a._window = _FakeWindow()
    a.window_minimize()
    assert a.window_toggle_maximize() == {"custom": False, "maximized": False}
    a.resize_begin("e", 1.0)
    assert a._resize is None and a._window.calls == []


def test_resize_flow_ignores_stale_calls_and_bad_edges(api):
    api.resize_begin("se", 1.0)
    api.resize_to("se", 50, 40, 1)
    assert api.state["rect"] == (100, 200, 1050, 740)
    api.resize_to("se", 10, 10, 1)                 # 重複／過期的序號：丟掉（橋接可能亂序）
    api.resize_to("se", 5, 5, 0)
    assert api.state["rect"] == (100, 200, 1050, 740)
    api.resize_to("zz", 99, 99, 2)                 # 不合法的邊緣：忽略
    assert api.state["rect"] == (100, 200, 1050, 740)
    api.resize_to("se", 60, 50, 3)                 # 位移是相對「開始時」的範圍，不是累加
    assert api.state["rect"] == (100, 200, 1060, 750)
    api.resize_end()
    api.resize_to("se", 500, 500, 4)               # 結束後不再縮放
    assert api.state["rect"] == (100, 200, 1060, 750)


def test_resize_minimum_scales_with_dpi(api):
    api.resize_begin("e", 1.5)                     # 150% 縮放：最小寬度（邏輯像素）× 1.5 = 實體像素
    api.resize_to("e", -800, 0, 1)
    assert api.state["rect"][2] == int(cli.MIN_WINDOW_SIZE[0] * 1.5)


class _FakeUser32:
    def __init__(self, ok):
        self.ok, self.calls = ok, []

    def SetProcessDpiAwarenessContext(self, ctx):
        self.calls.append(ctx.value)
        return 1 if self.ok else 0


class _FakeShcore:
    def __init__(self, result):
        self.result, self.calls = result, []

    def SetProcessDpiAwareness(self, level):
        self.calls.append(level)
        return self.result


def test_desktop_declares_per_monitor_v2_dpi_awareness():
    """pywebview 只會宣告「系統 DPI 感知」。多螢幕縮放不同時，每螢幕感知的視窗管理程式（PowerToys、mvapp）
    用實體像素指定位置與大小，系統再替系統感知的視窗縮放一次，就會「位置對、大小不對」。
    所以要在建立視窗之前先宣告成每螢幕感知（PerMonitorV2 = -4）。"""
    u, s = _FakeUser32(ok=True), _FakeShcore(0)
    assert cli._enable_per_monitor_dpi(u, s) is True
    import ctypes

    assert u.calls == [ctypes.c_void_p(-4).value] and s.calls == []   # 成功就不必再退而求其次（-4 在 64 位元上讀出來是無號數）
    # 舊系統不支援 PerMonitorV2：退回每螢幕感知（Windows 8.1）
    u, s = _FakeUser32(ok=False), _FakeShcore(0)
    assert cli._enable_per_monitor_dpi(u, s) is True and s.calls == [2]
    # 已經被設定過（例如打包時的 manifest）：回 False，但不丟例外
    u, s = _FakeUser32(ok=False), _FakeShcore(-2147024891)       # E_ACCESSDENIED
    assert cli._enable_per_monitor_dpi(u, s) is False


def test_per_monitor_dpi_is_enabled_before_the_window_is_created():
    import inspect

    src = inspect.getsource(cli.run_desktop)
    assert src.index("_enable_per_monitor_dpi()") < src.index("webview.create_window")


@pytest.mark.skipif(sys.platform != "win32", reason="Zone.Identifier 是 NTFS 的功能")
def test_unblock_clears_the_internet_zone_mark_from_bundled_dlls(tmp_path, monkeypatch):
    """從 GitHub 下載 ZIP 再解壓縮，檔案會帶「來自網際網路」標記；.NET Framework 拒絕載入這種 DLL，
    pythonnet 載入 Python.Runtime.dll 失敗，桌面視窗開不起來。啟動時要先把標記清掉（實測重現並驗證過）。"""
    mark = b"[ZoneTransfer]\r\nZoneId=3\r\n"
    dll = tmp_path / "pythonnet" / "runtime" / "Python.Runtime.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"MZ")
    other = tmp_path / "other.dll"; other.write_bytes(b"MZ")
    clean = tmp_path / "clean.dll"; clean.write_bytes(b"MZ")        # 本來就沒有標記
    for f in (dll, other):
        (f.parent / (f.name + ":Zone.Identifier")).write_bytes(mark)  # 寫入 NTFS 的替代資料流
    assert Path(f"{dll}:Zone.Identifier").read_bytes() == mark

    monkeypatch.setattr(config, "FROZEN", False)
    assert cli._unblock_bundled_files() == 0                        # 不是打包版：什麼都不做

    assert cli._unblock_bundled_files(tmp_path) == 2
    for f in (dll, other):
        assert not Path(f"{f}:Zone.Identifier").exists()
        assert f.read_bytes() == b"MZ"                              # 檔案本身沒被動到
    assert cli._unblock_bundled_files(tmp_path) == 0                # 再跑一次：沒有東西可清，也不會出錯


def test_no_unblock_switch_disables_clearing(tmp_path, monkeypatch):
    """CI 的對照組：設了 TUBETRAN_NO_UNBLOCK 就不清標記（用來證明測試真的抓得到「帶標記就載入失敗」）。"""
    monkeypatch.setenv("TUBETRAN_NO_UNBLOCK", "1")
    assert cli._unblock_bundled_files(tmp_path) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="pythonnet 只在 Windows")
def test_selftest_really_loads_pythonnet_and_fails_when_it_cannot(monkeypatch, capsys):
    """只 import webview 看不出 .NET 載入有沒有問題（pythonnet 要到開視窗才載入），
    所以 --selftest 要實際載入 pythonnet；載入失敗就必須回報失敗。"""
    import types

    fake = types.ModuleType("clr")
    def boom(name):
        raise RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize")
    fake.AddReference = boom
    monkeypatch.setitem(sys.modules, "clr", fake)
    assert cli.selftest() == 1
    out = capsys.readouterr().out
    assert '"pythonnet_clr": "FAIL: RuntimeError' in out and '"unblocked_dlls"' in out


def test_desktop_failure_dialog_explains_how_to_unblock():
    text = cli._desktop_failure_text(RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize"),
                                     r"C:\PortableApps\TubeTran", r"C:\x\tubetran.log")
    assert "Python.Runtime.Loader.Initialize" in text and "解除封鎖" in text and "Unblock-File" in text
    assert r"Get-ChildItem" in text and r"C:\PortableApps\TubeTran" in text and "--server" in text
    assert "Unblock" in text.split("TubeTran could not")[1]          # 英文說明也在


def test_unblock_runs_before_pywebview_loads_pythonnet():
    import inspect

    src = inspect.getsource(cli.run_desktop)
    assert src.index("_unblock_bundled_files()") < src.index("import webview")


def test_min_window_size_is_small_enough_for_window_managers():
    """視窗管理程式（平鋪／貼齊）會直接指定大小；比最小值小的要求會被擋住，變成「位置對了、大小沒變」。
    曾經最小寬度 900，要排成約 580 寬的格子就失敗。窄到這個程度版面要仍可用（見 test_style 的斷言）。"""
    assert cli.MIN_WINDOW_SIZE[0] <= 400 and cli.MIN_WINDOW_SIZE[1] <= 300


def test_system_maximize_is_detected_and_restored_with_the_system_restore(api, monkeypatch):
    """Win+↑、拖到螢幕上緣貼齊、FancyZones 最大化，都是系統的最大化（IsZoomed）；
    按鈕要顯示成「還原」，按下去要用系統的還原（回到最大化之前的位置與大小）。"""
    zoomed, restored = {"v": True}, []
    monkeypatch.setattr(winctl, "is_zoomed", lambda hwnd: zoomed["v"])
    monkeypatch.setattr(winctl, "restore", lambda hwnd: (restored.append(hwnd), zoomed.update(v=False)))
    assert api.window_state()["maximized"] is True
    assert api.window_toggle_maximize()["maximized"] is False
    assert restored == [1234]
    assert api.window_state()["maximized"] is False


def test_maximized_flag_is_dropped_when_the_window_is_changed_externally(api):
    api.window_toggle_maximize()
    assert api.window_state()["maximized"] is True
    api.state["rect"] = (0, 0, 960, 1040)          # 視窗管理程式把它排成左半邊
    assert api.window_state()["maximized"] is False
    api.resize_begin("e", 1.0)                     # 旗標放掉後，縮放不再被擋住
    assert api._resize is not None


def test_toggle_after_external_change_maximizes_again_instead_of_restoring(api):
    api.window_toggle_maximize()
    api.state["rect"] = (0, 0, 960, 1040)          # 外部改過；旗標過期
    assert api.window_toggle_maximize()["maximized"] is True   # 這次應該是「最大化」，不是「還原」
    assert api.state["rect"] == (0, 0, 1920, 1040)
    assert api._normal_rect == (0, 0, 960, 1040)   # 還原時回到外部排好的位置


def test_same_rect_tolerance():
    assert winctl.same_rect((0, 0, 100, 100), (1, -1, 101, 99))
    assert not winctl.same_rect((0, 0, 100, 100), (0, 0, 100, 110))


def test_no_resize_while_maximized(api):
    api.window_toggle_maximize()
    api.resize_begin("e", 1.0)
    assert api._resize is None


MONITOR = (0, 0, 1920, 1080)
WORK = (0, 0, 1920, 1040)  # 底下有 40px 的工作列


def test_client_rect_is_the_whole_window_so_no_frame_is_drawn():
    """WS_THICKFRAME 之下，客戶區要涵蓋整個視窗（不畫邊框）。"""
    assert winctl.client_rect_for_zoomed((100, 100, 900, 700), MONITOR, WORK, zoomed=False) == (100, 100, 900, 700)


def test_client_rect_of_a_system_maximized_window_is_clamped_to_the_work_area():
    """系統最大化時 Windows 讓視窗往螢幕外多出一圈邊框，客戶區要縮回工作區（取交集，不依賴邊框厚度）。"""
    for overhang in (7, 8, 14, 16):
        proposed = (-overhang, -overhang, 1920 + overhang, 1040 + overhang)
        assert winctl.client_rect_for_zoomed(proposed, MONITOR, WORK, zoomed=True) == WORK


def test_client_rect_of_fullscreen_is_left_alone():
    """全螢幕（範圍剛好是整個螢幕、含工作列區域）不能被縮進工作區，否則底下會露出一條工作列。"""
    assert winctl.client_rect_for_zoomed(MONITOR, MONITOR, WORK, zoomed=True) == MONITOR


@pytest.mark.skipif(sys.platform != "win32", reason="只有 Windows 有 user32")
def test_winctl_does_not_change_the_shared_user32_function_signatures():
    """ctypes.windll.user32 是整個程序共用的物件。若在上面設定 argtypes，pywebview 自己呼叫
    SetWindowPos 時（移動視窗時傳 None 表示不改大小）會拋出
    ArgumentError: argument 5: 'NoneType' object cannot be interpreted as an integer，
    結果是「縮放或最大化過一次之後就無法拖曳視窗」。所以必須用自己專屬的 WinDLL 實例。"""
    import ctypes

    winctl._user32()  # 觸發 argtypes 設定
    shared = ctypes.windll.user32
    for name in ("SetWindowPos", "GetWindowRect", "MonitorFromWindow", "GetMonitorInfoW", "FindWindowW",
                 "GetWindowLongW", "SetWindowLongW", "GetWindowLongPtrW", "SetWindowLongPtrW", "CallWindowProcW", "IsZoomed"):
        assert getattr(shared, name).argtypes is None, f"共用的 user32.{name} 被設定了 argtypes"
    # pywebview 移動視窗時的呼叫方式（cx、cy 傳 None）要能正常通過參數檢查
    hwnd = shared.GetDesktopWindow()
    shared.SetWindowPos(hwnd, None, None, None, None, None, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0200)  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|NOOWNERZORDER


def test_window_does_not_scroll_only_the_area_below_the_toolbar_does():
    """視窗本身不捲動、只有頂欄下方的 .page-scroll 捲動。
    若改回由 <html> 捲動，視窗最外緣約 15px 會是瀏覽器捲軸，滑鼠事件被它吸走，
    桌面版右邊與右下角的縮放把手就抓不到（用真實滑鼠實測過）。"""
    from tubetran import config

    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "html, body { height: 100%; overflow: hidden; }" in css
    assert ".page-scroll { flex: 1; min-height: 0; overflow-x: hidden; overflow-y: auto; }" in css
    assert 'class="page-scroll"' in html and html.index('class="topbar"') < html.index('class="page-scroll"')


def test_narrow_layout_keeps_the_url_row_aligned_with_the_content_area():
    """窄螢幕時網址列換到第二行，它的右緣要和下方播放區的右緣對齊（左緣本來就對齊）。
    內容區右緣 = 視窗右緣 − 捲軸寬度 − 14px 內距；捲軸寬度由 app.js 量出放進 --sbw。
    桌面版無框模式的頂欄右內距是 0（讓視窗按鈕貼齊邊緣），要自己補 14px。（版面數值用 Edge 實測過，差 0px）"""
    from tubetran import config

    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "margin-right: var(--sbw, 0px)" in css
    assert ".custom-chrome #form { margin-right: calc(14px + var(--sbw, 0px)); }" in css
    assert '"--sbw"' in js and "ResizeObserver" in js


def test_js_api_does_not_expose_internal_state():
    """pywebview 會把 js_api 的公開屬性都暴露給網頁，內部狀態必須是底線開頭。"""
    public = {n for n in dir(cli._DesktopApi(True)) if not n.startswith("_")}
    assert public == {"set_fullscreen", "cursor_pos", "logo_fraction", "fullscreen_key_down", "window_state", "window_minimize", "window_toggle_maximize",
                      "window_move_begin", "window_move_end", "window_close", "resize_begin", "resize_to", "resize_end"}
