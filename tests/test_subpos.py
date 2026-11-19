"""字幕高低位置（static/subpos.js）：播放時 Alt+↑ / Alt+↓ 調整，視窗與全螢幕各記一個位置。純函式，用 Node 直接執行測試。"""
import json
import shutil
import subprocess
import sys

import pytest

from tubetran import config

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def _run(expr: str, arg=None):
    """在 Node 裡載入 subpos.js，S 是它的匯出；expr 是用 S 與 a（傳入的參數）寫成的運算式，結果以 JSON 回傳。"""
    script = f"const S = require(process.argv[1]); const a = JSON.parse(process.argv[2]); console.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "subpos.js"), json.dumps(arg)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def key(k, **mods):
    return {"key": k, **mods}


@needs_node
def test_alt_up_and_alt_down_move_the_subtitles():
    assert _run("[S.subKey(a[0], null), S.subKey(a[1], null)]",
                [key("ArrowUp", altKey=True), key("ArrowDown", altKey=True)]) == [1, -1]
    # 其他按鍵、左右鍵都不是
    other = [key("ArrowLeft", altKey=True), key("ArrowRight", altKey=True), key("f", altKey=True), key("PageUp", altKey=True)]
    assert _run("a.map(e => S.subKey(e, null))", other) == [0] * 4


@needs_node
def test_plain_arrows_are_left_to_youtube_and_the_page():
    """單純的 ↑ ↓ 是 YouTube 的音量快捷鍵（也是捲動頁面、輸入框、下拉選單的按鍵），不能攔截；這就是要用 Alt 組合鍵的原因。"""
    assert _run("a.map(e => S.subKey(e, null))", [key("ArrowUp"), key("ArrowDown")]) == [0, 0]


@needs_node
def test_alt_arrows_combined_with_other_modifiers_or_composing_are_left_alone():
    """Alt 加上 Ctrl／Meta／Shift 是別的快捷鍵（AltGr 在 Windows 會同時回報 Ctrl 與 Alt）；輸入法選字中也不能搶。"""
    cases = [key("ArrowUp", altKey=True, ctrlKey=True), key("ArrowDown", altKey=True, metaKey=True),
             key("ArrowDown", altKey=True, shiftKey=True), key("ArrowUp", altKey=True, isComposing=True)]
    assert _run("a.map(e => S.subKey(e, null))", cases) == [0] * 4


@needs_node
def test_alt_arrows_work_while_typing_except_where_alt_down_opens_a_list():
    """Alt+方向鍵在輸入框裡沒有別的用途，打字時（網址、搜尋、書籤名稱）照樣可以調整字幕位置、也可以在單選鈕與按鈕上；
    例外是 Alt+↓ 會展開清單的元素：下拉選單、附建議清單（datalist）的輸入框（標籤輸入框）。"""
    ok = [{"tagName": "INPUT", "type": "text"}, {"tagName": "INPUT", "type": "search"}, {"tagName": "TEXTAREA"},
          {"tagName": "INPUT", "type": "radio"}, {"tagName": "BUTTON"}, {"tagName": "BODY"}, {"tagName": "IFRAME"}]
    assert _run("a.map(el => S.subKey({ key: 'ArrowUp', altKey: true }, el))", ok) == [1] * 7
    taken = [{"tagName": "SELECT"}, {"tagName": "INPUT", "type": "text", "list": {}},
             {"tagName": "INPUT", "type": "text", "getAttribute": None}]
    # getAttribute 在 JSON 裡只能是 null：下面用函式版補測「有 list 屬性」的情形
    assert _run("[S.subKey({ key: 'ArrowDown', altKey: true }, a[0]), S.subKey({ key: 'ArrowDown', altKey: true }, a[1])]", taken) == [0, 0]
    assert _run("S.subKey({ key: 'ArrowDown', altKey: true }, { tagName: 'INPUT', getAttribute: (n) => (n === 'list' ? 'tag-suggest' : null) })") == 0
    assert _run("S.subKey({ key: 'ArrowDown', altKey: true }, { tagName: 'INPUT', getAttribute: () => null })") == -1


@needs_node
def test_position_moves_in_steps_and_stays_inside_the_player():
    assert _run("S.moveBottom(54, 1, 500)") == 54 + _run("S.STEP")         # ↑：往上
    assert _run("S.moveBottom(54, -1, 500)") == 54 - _run("S.STEP")        # ↓：往下
    assert _run("S.moveBottom(2, -1, 500)") == 0                           # 不能低於播放區底部
    assert _run("S.moveBottom(399, 1, 500)") == 400                        # 最高到播放區高度的 80%
    assert _run("S.moveBottom(400, 1, 500)") == 400
    assert _run("S.clampBottom(-30, 500)") == 0 and _run("S.clampBottom(30.6, 500)") == 31   # 取整數像素
    assert _run("S.clampBottom(30, 0)") == 0                               # 還量不到播放區高度：不亂動


@needs_node
def test_holding_the_key_repeats_after_a_delay_in_polling_mode():
    """桌面版焦點在影片裡時由 Python 回報按著哪個鍵：剛按下立刻移動一次，按住超過 350ms 後每 50ms 移動一次，放開重置。"""
    steps = [[1, 0], [1, 100], [1, 349], [1, 350], [1, 380], [1, 400], [1, 450], [0, 460], [1, 470], [-1, 480], [-1, 520]]
    got = _run("(() => { const st = { dir: 0, since: 0, last: 0 }; return a.map(([d, t]) => S.repeatStep(st, d, t)); })()", steps)
    assert got == [True, False, False, True, False, True, True, False, True, True, False]
    assert _run("S.REPEAT_DELAY") == 350 and _run("S.REPEAT_EVERY") == 50


@needs_node
def test_stored_positions_are_read_defensively():
    assert _run("S.parseStored(a)", '{"win": 80, "fs": 120.5}') == {"win": 80, "fs": 120.5}
    assert _run("S.parseStored(a)", '{"win": 80}') == {"win": 80, "fs": None}         # 只調整過其中一種畫面
    assert _run("S.parseStored(a)", '{"win": -5, "fs": "x"}') == {"win": None, "fs": None}
    assert _run("S.parseStored(a)", "{壞掉") == {"win": None, "fs": None}
    assert _run("S.parseStored(a)", None) == {"win": None, "fs": None}
    assert _run("S.parseStored(a)", "null") == {"win": None, "fs": None}


# ── 桌面版：焦點在 YouTube 的 iframe 裡時，由 Python 回報 ↑ ↓ ──
@pytest.fixture
def key_api(monkeypatch):
    from tubetran import cli, winctl

    monkeypatch.setattr(sys, "platform", "win32")
    a = cli._DesktopApi(custom_chrome=True)
    a._window = object()
    a._hwnd = lambda: 1234
    state = {"fg": 1234, "down": set()}
    monkeypatch.setattr(winctl, "foreground_window", lambda: state["fg"])
    monkeypatch.setattr(winctl, "key_down", lambda vk: vk in state["down"])
    return a, state


ALT = 0x12


def test_subtitle_key_reports_only_alt_up_and_alt_down_when_our_window_is_in_front(key_api):
    a, st = key_api
    assert a.subtitle_key() == 0                       # 沒按
    st["down"] = {ALT, 0x26}
    assert a.subtitle_key() == 1                       # Alt+↑
    st["down"] = {ALT, 0x28}
    assert a.subtitle_key() == -1                      # Alt+↓
    st["down"] = {ALT, 0x26, 0x28}
    assert a.subtitle_key() == 0                       # 同時按兩個方向：不動
    st["down"] = {ALT, 0x26}
    st["fg"] = 9999
    assert a.subtitle_key() == 0                       # 別的視窗在前景：在別的程式裡按 Alt+↑ 不能影響我們
    st["fg"] = 0
    assert a.subtitle_key() == 0


def test_plain_arrows_are_not_reported_so_youtubes_volume_keys_are_untouched(key_api):
    a, st = key_api
    for arrow in (0x26, 0x28):                         # 單純的 ↑ ↓ 是 YouTube 的音量：不回報
        st["down"] = {arrow}
        assert a.subtitle_key() == 0, hex(arrow)


def test_subtitle_key_ignores_other_keys_and_modifier_combinations(key_api):
    a, st = key_api
    for other in (0x25, 0x27, 0x46, 0x20, 0x0D):       # Alt 加 ←、→、F、空白、Enter
        st["down"] = {ALT, other}
        assert a.subtitle_key() == 0, hex(other)
    for mod in (0x10, 0x11, 0x5B, 0x5C):               # 再加 Shift、Ctrl（AltGr 也算）、左 Win、右 Win：別的快捷鍵
        st["down"] = {ALT, 0x26, mod}
        assert a.subtitle_key() == 0, hex(mod)


def test_subtitle_key_is_zero_on_unsupported_platforms_or_without_a_window(monkeypatch):
    from tubetran import cli

    a = cli._DesktopApi()
    assert a.subtitle_key() == 0                       # 沒有視窗
    monkeypatch.setattr(sys, "platform", "linux")
    a._window = object()
    assert a.subtitle_key() == 0                       # 不支援的系統


# ── 網頁接線 ──
def test_page_wires_subtitle_position_per_screen_mode_and_persists_it():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert html.index("subpos.js") < html.index("app.js")                      # 邏輯要先載入
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'document.fullscreenElement || pseudoFs ? "fs" : "win"' in js        # 視窗與全螢幕（含 macOS 的 pseudo）各一個位置
    assert 'addEventListener("fullscreenchange", applySubPos)' in js            # 進出全螢幕換成另一個位置
    assert "--sub-bottom" in js and "localStorage.setItem(SUBPOS_KEY" in js     # 記下來
    assert "if (!dir || !segs.length) return" in js and "e.preventDefault()" in js  # 還沒有字幕時不攔截
    # 桌面版焦點在影片裡：輪詢 Alt+↑ / Alt+↓。用 Alt 組合鍵就不會和 YouTube 的音量快捷鍵衝突，不需要還原音量
    assert "subtitle_key" in js and 'tagName !== "IFRAME"' in js
    assert "setVolume" not in js
