"""全螢幕鈕何時顯示（static/fsbutton.js）：跟著 YouTube 控制列。邏輯是純函式，用 Node 直接執行測試。"""
import json
import re
import shutil
import subprocess
import sys

import pytest

from tubetran import config

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def _run(cases: list[dict]) -> list[bool]:
    script = (
        "const { fsShouldShow } = require(process.argv[1]);"
        "const cases = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(cases.map(c => fsShouldShow("
        "{ inside: c.inside, lastActivity: c.lastActivity, leftAt: c.leftAt, overButton: c.overButton }, "
        "c.now, c.paused, c.track, c.logo))));"
    )
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "fsbutton.js"), json.dumps(cases)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def case(**kw):
    base = dict(inside=True, lastActivity=0, leftAt=-1e9, now=0, paused=False, track=True, overButton=False, logo=None)
    return {**base, **kw}


# ── 偵測得到 YouTube 字樣：完全跟著它 ──
@needs_node
def test_follows_the_youtube_wordmark_exactly():
    """字樣在（白色比例約 0.36）就顯示，不在（約 0）就隱藏；和滑鼠在哪裡、停了多久、播放或暫停都無關。"""
    assert _run([case(logo=0.36), case(logo=0.0), case(logo=0.36, inside=False, now=99_999, leftAt=0),
                 case(logo=0.0, inside=True, paused=True), case(logo=0.36, paused=True)]) == [True, False, True, False, True]


@needs_node
def test_a_mostly_white_area_is_not_mistaken_for_the_wordmark():
    """整塊都是白的畫面（白牆、白色字幕底圖）比例接近 1，不是字樣，不能當成控制列還在。"""
    assert _run([case(logo=0.95), case(logo=1.0), case(logo=0.10), case(logo=0.30), case(logo=0.45)]) == \
        [False, False, False, True, True]


@needs_node
def test_a_single_odd_reading_does_not_make_the_button_flicker():
    """偶發的單次異常值（例如截圖瞬間畫面被重畫成全白）不能讓按鈕閃爍：要連續兩次讀不到才算字樣消失。"""
    script = ("const { fsLogoReading } = require(process.argv[1]); const c = JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(c.map(([cur, prev]) => fsLogoReading(cur, prev))));")
    cases = [[1.0, 0.36], [0.0, 0.36], [0.36, 0.0], [0.0, 0.0], [1.0, 1.0], [0.36, 0.36], [None, 0.36], [0.5, None]]
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "fsbutton.js"), json.dumps(cases)],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(out.stdout) == [0.36, 0.36, 0.36, 0.0, 1.0, 0.36, None, 0.5]
    # 上一次在、這次不在 → 沿用上一次（還在）；連續兩次都不在 → 才採用「不在」


@needs_node
def test_mouse_over_the_button_keeps_it_even_when_the_wordmark_is_gone():
    assert _run([case(logo=0.0, overButton=True), case(logo=None, inside=False, now=99_999, overButton=True)]) == [True, True]


# ── 偵測不到：退回用時間估計（實測 YouTube 在滑鼠停止後約 4 秒才收起控制列）──
@needs_node
def test_fallback_hides_about_4_seconds_after_the_mouse_stops_while_playing():
    assert _run([case(now=1000), case(now=3900), case(now=4000), case(now=4100), case(now=20_000)]) == \
        [True, True, False, False, False]


@needs_node
def test_fallback_keeps_it_about_4_seconds_after_the_mouse_leaves():
    assert _run([case(inside=False, leftAt=5000, now=5000), case(inside=False, leftAt=5000, now=8900),
                 case(inside=False, leftAt=5000, now=9100)]) == [True, True, False]


@needs_node
def test_fallback_paused_stays_while_inside_and_without_motion_tracking_it_never_hides_inside():
    assert _run([case(paused=True, now=60_000)]) == [True]
    # 瀏覽器收不到 iframe 內的滑鼠移動，無法判斷「不動」：在裡面就一直顯示，否則隱藏後使用者動滑鼠也叫不出來
    assert _run([case(track=False, now=60_000)]) == [True]


# ── 桌面版的 Python 端 ──
@pytest.mark.skipif(sys.platform != "win32", reason="GetCursorPos 只在 Windows")
def test_cursor_pos_returns_screen_coordinates():
    from tubetran import winctl

    x, y = winctl.cursor_pos()
    assert isinstance(x, int) and isinstance(y, int) and -20_000 < x < 20_000 and -20_000 < y < 20_000


def test_cursor_pos_is_none_on_unsupported_platforms(monkeypatch):
    from tubetran import cli

    monkeypatch.setattr(sys, "platform", "linux")
    assert cli._DesktopApi().cursor_pos() is None
    assert cli._DesktopApi().logo_fraction(0, 0, 10, 10, 1) is None


def test_white_fraction_counts_near_white_pixels():
    from tubetran import winctl

    w = h = 8
    all_white = bytes([255, 255, 255, 255]) * (w * h)
    all_black = bytes([0, 0, 0, 255]) * (w * h)
    assert winctl.white_fraction(all_white, w, h, 1) == 1.0 and winctl.white_fraction(all_black, w, h, 1) == 0.0
    # 前半白、後半黑 → 約一半
    half = bytes([255, 255, 255, 255]) * (w * h // 2) + bytes([0, 0, 0, 255]) * (w * h // 2)
    assert winctl.white_fraction(half, w, h, 1) == 0.5
    # 灰色（低於門檻）不算白；只有其中一個通道不夠亮也不算
    assert winctl.white_fraction(bytes([200, 200, 200, 255]) * (w * h), w, h, 1) == 0.0
    assert winctl.white_fraction(bytes([255, 255, 100, 255]) * (w * h), w, h, 1) == 0.0
    # 抽樣（step=2）與逐點結果接近；資料長度不足或尺寸不合理時回 0 而不是丟例外
    assert winctl.white_fraction(all_white, w, h, 2) == 1.0
    assert winctl.white_fraction(b"", w, h) == 0.0 and winctl.white_fraction(all_white, 0, h) == 0.0


@pytest.fixture
def api_with_window(monkeypatch):
    from tubetran import cli, winctl

    monkeypatch.setattr(sys, "platform", "win32")
    a = cli._DesktopApi(custom_chrome=True)
    a._window = object()
    a._hwnd = lambda: 1234
    calls = []
    monkeypatch.setattr(winctl, "is_iconic", lambda h: False)
    monkeypatch.setattr(winctl, "client_origin", lambda h: (100, 50))          # 客戶區左上角在螢幕 (100, 50)
    monkeypatch.setattr(winctl, "get_rect", lambda h: (100, 50, 1600, 1000))   # 視窗範圍 x 100..1700、y 50..1050（實體像素）
    monkeypatch.setattr(winctl, "screen_white_fraction", lambda *args: calls.append(args) or 0.36)
    return a, calls


def test_logo_fraction_converts_css_px_to_screen_px(api_with_window):
    a, calls = api_with_window
    assert a.logo_fraction(700, 400, 86, 22, 1.5) == 0.36
    assert calls == [(100 + 1050, 50 + 600, 129, 33)]                      # 客戶區原點 + CSS px × dpr


def test_logo_fraction_refuses_to_look_outside_our_own_window(api_with_window):
    """不能被拿來截取螢幕上別的地方（例如別的應用程式的畫面）。"""
    a, calls = api_with_window
    assert a.logo_fraction(-5, 10, 50, 20, 1) is None                      # 超出左邊
    assert a.logo_fraction(1580, 10, 50, 20, 1) is None                    # 超出右邊
    assert a.logo_fraction(10, 990, 50, 20, 1) is None                     # 超出下邊
    assert a.logo_fraction(10, -10, 50, 20, 1) is None                     # 超出上邊
    assert a.logo_fraction(10, 10, 50, 20, 1) == 0.36                      # 在裡面就可以
    assert len(calls) == 1


def test_logo_fraction_rejects_unreasonable_arguments(api_with_window):
    a, calls = api_with_window
    for bad in ((0, 0, 0, 10, 1), (0, 0, 10, 0, 1), (0, 0, 5000, 10, 1), (0, 0, 10, 5000, 1), (0, 0, 10, 10, 0),
                (0, 0, 10, 10, 100), (float("nan"), 0, 10, 10, 1), ("x", 0, 10, 10, 1), (None, 0, 10, 10, 1)):
        assert a.logo_fraction(*bad) is None, bad
    assert calls == []


def test_logo_fraction_is_none_when_the_window_is_minimized(api_with_window, monkeypatch):
    from tubetran import winctl

    a, calls = api_with_window
    monkeypatch.setattr(winctl, "is_iconic", lambda h: True)
    assert a.logo_fraction(10, 10, 50, 20, 1) is None and calls == []


# ── F 快捷鍵 ──
@needs_node
def test_f_hotkey_filter():
    """F 切換全螢幕；但在輸入框裡打字、Ctrl+F 之類的組合鍵、按住不放、輸入法組字中，都不能觸發。"""
    script = ("const { fsHotkey } = require(process.argv[1]); const c = JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(c.map(([e, tag]) => fsHotkey(e, tag))));")
    f = {"key": "f"}
    cases = [
        [f, "BODY"], [{"key": "F"}, "BODY"], [f, "IFRAME"], [f, "DIV"], [f, ""], [f, None],      # 一般情況：會
        [f, "INPUT"], [f, "TEXTAREA"], [f, "SELECT"],                                             # 在輸入欄位裡打字：不會
        [{"key": "f", "ctrlKey": True}, "BODY"], [{"key": "f", "altKey": True}, "BODY"],          # 組合鍵：不會
        [{"key": "f", "metaKey": True}, "BODY"], [{"key": "f", "repeat": True}, "BODY"],          # 按住不放：不會
        [{"key": "f", "isComposing": True}, "BODY"], [{"key": "g"}, "BODY"], [{"key": "Enter"}, "BODY"], [None, "BODY"],
    ]
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "fsbutton.js"), json.dumps(cases)],
                         capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(out.stdout) == [True, True, True, True, True, True,
                                      False, False, False,
                                      False, False, False, False, False, False, False, False]


@pytest.fixture
def key_api(monkeypatch):
    """假的視窗與假的鍵盤狀態：可以指定誰在前景、哪些鍵被按著。"""
    from tubetran import cli, winctl

    monkeypatch.setattr(sys, "platform", "win32")
    a = cli._DesktopApi(custom_chrome=True)
    a._window = object()
    a._hwnd = lambda: 1234
    state = {"fg": 1234, "down": set()}
    monkeypatch.setattr(winctl, "foreground_window", lambda: state["fg"])
    monkeypatch.setattr(winctl, "key_down", lambda vk: vk in state["down"])
    return a, state


def test_f_key_is_reported_only_when_our_window_is_in_front(key_api):
    """只回報「F」一個鍵，而且只有我們的視窗在最前面時才可能是 True：在別的程式裡打 F 不會觸發我們的全螢幕。"""
    a, st = key_api
    assert a.fullscreen_key_down() is False                  # 沒按
    st["down"] = {0x46}
    assert a.fullscreen_key_down() is True                   # 按著 F、我們在前景
    st["fg"] = 9999
    assert a.fullscreen_key_down() is False                  # 別的視窗在前景
    st["fg"] = 0
    assert a.fullscreen_key_down() is False                  # 沒有前景視窗


def test_f_key_ignores_other_keys_and_modifier_combinations(key_api):
    a, st = key_api
    for other in (0x41, 0x47, 0x20, 0x0D):                    # A、G、空白、Enter
        st["down"] = {other}
        assert a.fullscreen_key_down() is False, hex(other)
    for mod in (0x11, 0x12, 0x5B, 0x5C):                      # Ctrl、Alt、左 Win、右 Win（Ctrl+F 是搜尋，Win+F 是系統功能）
        st["down"] = {0x46, mod}
        assert a.fullscreen_key_down() is False, hex(mod)
    st["down"] = {0x46, 0x10}                                 # Shift+F 與大寫 F 一樣算
    assert a.fullscreen_key_down() is True


def test_f_key_is_false_on_unsupported_platforms_or_without_a_window(monkeypatch):
    from tubetran import cli

    a = cli._DesktopApi()
    assert a.fullscreen_key_down() is False                   # 沒有視窗
    monkeypatch.setattr(sys, "platform", "linux")
    a._window = object()
    assert a.fullscreen_key_down() is False                   # 不支援的系統


def test_page_polls_the_f_key_only_while_the_video_iframe_has_focus():
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "fullscreen_key_down" in js and 'tagName !== "IFRAME"' in js    # 焦點在 iframe 時才輪詢；平常走 keydown
    assert "down && !prev" in js                                           # 只在「剛按下」時切換，按住不放不會一直切


def test_page_wires_the_wordmark_detection_and_avoids_its_own_subtitles():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert html.index("fsbutton.js") < html.index("app.js")                 # 邏輯要先載入
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "#stage:hover #fs" not in css                                    # 不再靠 :hover（滑鼠一離開就立刻消失）
    assert "#stage.active #fs" in css
    # 隱藏時也要接收滑鼠（否則游標落在 YouTube 膠囊上，鈕不會出現、點了是點到膠囊），但範圍只到「YouTube」字樣的右邊，不吃掉字樣的連結
    assert not re.search(r"#fs\s*\{[^}]*pointer-events:\s*none", css)
    m = re.search(r"#fs::before\s*\{[^}]*width:\s*(\d+)px", css)
    assert m and int(m.group(1)) <= 58                                      # 字樣右緣離播放區右邊約 58～60px
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "fsShouldShow" in js and "cursor_pos" in js and "logo_fraction" in js
    assert "subtitleCoversLogo" in js                                       # 我們的字幕蓋住那塊區域時，不能用偵測結果
    assert "fsLogoReading" in js                                            # 防抖
