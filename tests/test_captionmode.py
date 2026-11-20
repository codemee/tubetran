"""字幕模式快捷鍵 C 與記憶（static/fsbutton.js、app.js）：雙語 → 原文 → 譯文 → 無。純函式用 Node 直接執行測試。"""
import json
import shutil
import subprocess
import sys

import pytest

from tubetran import config

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def _run(expr: str, arg=None):
    script = f"const S = require(process.argv[1]); const a = JSON.parse(process.argv[2]); console.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "fsbutton.js"), json.dumps(arg)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


@needs_node
def test_modes_cycle_in_order_and_wrap_around():
    assert _run("['both', 'orig', 'trans', 'none'].map(S.nextCaptionMode)") == ["orig", "trans", "none", "both"]
    assert _run("S.nextCaptionMode('壞掉')") == "both"      # 不認得的值回到雙語


@needs_node
def test_alt_c_hotkey_leaves_youtubes_own_c_alone():
    """單純的 C 是 YouTube 的開關字幕，不能攔截；這就是要用 Alt 組合鍵的原因。macOS 的 Option+C 會變成 ç，改認實體按鍵。"""
    assert _run("[S.captionHotkey({ key: 'c', altKey: true }), S.captionHotkey({ key: 'C', altKey: true })]") == [True, True]
    assert _run("S.captionHotkey({ key: 'ç', code: 'KeyC', altKey: true })") is True
    assert _run("[S.captionHotkey({ key: 'c' }), S.captionHotkey({ key: 'C', shiftKey: true })]") == [False, False]
    assert _run("S.captionHotkey({ key: 'f', altKey: true })") is False


@needs_node
def test_alt_c_hotkey_ignores_other_modifiers_and_repeat():
    for mod in ("ctrlKey", "metaKey", "shiftKey", "repeat", "isComposing"):   # AltGr 會同時回報 Ctrl 與 Alt
        assert _run("S.captionHotkey({ key: 'c', altKey: true, [a]: true })", mod) is False


@needs_node
def test_alt_b_hotkey_follows_the_same_rules_as_alt_c():
    assert _run("[S.bookmarkHotkey({ key: 'b', altKey: true }), S.bookmarkHotkey({ key: '∫', code: 'KeyB', altKey: true })]") == [True, True]
    assert _run("[S.bookmarkHotkey({ key: 'b' }), S.bookmarkHotkey({ key: 'c', altKey: true }), S.bookmarkHotkey({ key: 'b', altKey: true, ctrlKey: true }), S.bookmarkHotkey({ key: 'b', altKey: true, repeat: true })]") == [False] * 4
    assert _run("S.captionHotkey({ key: 'b', altKey: true })") is False     # 兩個快捷鍵互不干擾


@needs_node
def test_stored_mode_is_read_defensively():
    assert _run("['both', 'orig', 'trans', 'none'].map(S.parseCaptionMode)") == ["both", "orig", "trans", "none"]
    assert _run("[null, '', 'x', 'constructor'].map(S.parseCaptionMode)") == ["both"] * 4


# ── 桌面版：焦點在 YouTube 的 iframe 裡時，由 Python 回報 C ──
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


def test_alt_c_is_reported_only_in_our_front_window(key_api):
    a, st = key_api
    assert a.caption_key_down() is False
    st["down"] = {0x12, 0x43}
    assert a.caption_key_down() is True
    st["fg"] = 9999
    assert a.caption_key_down() is False                      # 別的視窗在前景
    st["fg"] = 1234
    st["down"] = {0x43}
    assert a.caption_key_down() is False                      # 單純的 C 是 YouTube 的開關字幕：不回報
    for other in (0x46, 0x41, 0x26):                          # Alt+F、Alt+A、Alt+↑
        st["down"] = {0x12, other}
        assert a.caption_key_down() is False, hex(other)
    for mod in (0x10, 0x11, 0x5B, 0x5C):                      # 再加 Shift、Ctrl（AltGr 也算）、左右 Win：別的快捷鍵
        st["down"] = {0x12, 0x43, mod}
        assert a.caption_key_down() is False, hex(mod)


def test_alt_b_is_reported_like_alt_c_but_the_two_do_not_mix(key_api):
    a, st = key_api
    st["down"] = {0x12, 0x42}
    assert a.bookmark_key_down() is True and a.caption_key_down() is False
    st["down"] = {0x12, 0x43}
    assert a.caption_key_down() is True and a.bookmark_key_down() is False
    st["down"] = {0x42}
    assert a.bookmark_key_down() is False                     # 沒按 Alt
    st["down"] = {0x12, 0x42, 0x11}
    assert a.bookmark_key_down() is False                     # AltGr／Ctrl+Alt+B
    st["down"] = {0x12, 0x42}
    st["fg"] = 9999
    assert a.bookmark_key_down() is False                     # 別的視窗在前景


def test_alt_keys_are_false_without_a_window_or_on_unsupported_platforms(monkeypatch):
    from tubetran import cli

    a = cli._DesktopApi()
    assert a.caption_key_down() is False and a.bookmark_key_down() is False
    monkeypatch.setattr(sys, "platform", "linux")
    a._window = object()
    assert a.caption_key_down() is False and a.bookmark_key_down() is False


# ── 網頁接線 ──
def test_page_wires_mode_button_hotkey_and_persistence():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="sm"' in html
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "#stage:fullscreen #fs-tools, #stage.pseudo-fs #fs-tools" in css   # 只在全螢幕出現（含 macOS 的 pseudo）
    assert "#stage.active #sm" in css                                 # 跟全螢幕鈕一起顯示／隱藏
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "captionHotkey(e)" in js and "caption_key_down" in js and "down && !prev" in js
    assert "setTimeout(applyNativeCaptions" not in js                 # Alt+C 不會被 YouTube 處理，不需要硬關它的字幕
    assert "localStorage.setItem(MODE_KEY" in js and "parseCaptionMode(localStorage.getItem(MODE_KEY))" in js
    assert 'addEventListener("change", () => setMode(r.value))' in js  # 工具列選項與浮動按鈕共用同一個入口


def test_page_wires_fullscreen_bookmark_list():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="sbm"' in html and 'id="fs-bm"' in html
    css = (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "#sbm[hidden] { display: none; }" in css and "gap: 20px" in css   # 沒有書籤時書籤鈕不占位置（flex 排列，字幕模式鈕永遠緊鄰音量）
    assert "#stage.active #sbm" in css                                                          # 跟全螢幕鈕一起顯示／隱藏
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "bookmarkHotkey(e) && bookmarks.length" in js and "bookmark_key_down" in js          # 沒有書籤時不攔截
    assert "setFsBm(false)" in js and "focusPlayerFrame" in js                                  # 跳轉／Esc 關閉、焦點還給播放器
    assert 'ArrowDown' in js                                                                    # 清單內用鍵盤選取
    assert 'keyboard?.lock' not in js and 'selfFsExit' not in js                                # 不處理 Esc：Esc 維持瀏覽器原本的退出全螢幕（試過攔截與接回都會把全螢幕弄亂）
    assert "全螢幕時工具列看不到" in js and 'class="bm-x"' in js and "fbm-item" in js
    assert "fbm-x" not in js                                                                    # 全螢幕清單不提供刪除


def test_iframe_key_poll_ignores_a_key_already_held_when_focus_arrives():
    """在書籤清單按 Alt+B 關閉時，焦點立刻還給播放器、Alt+B 還按著：輪詢不能把它當成新的一次按下，否則清單會馬上重開。"""
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "if (down && !prev && seen) onPress();" in js
    assert 'prev = false; seen = false; return;' in js                    # 焦點離開 iframe 就重置


@needs_node
def test_fullscreen_player_keys_map_to_youtube_shortcuts():
    """全螢幕時由我們處理的播放器快捷鍵：與 YouTube 的一致（Space／K、← →、J L、M、↑ ↓）。"""
    cases = {" ": {"toggle": True}, "k": {"toggle": True}, "K": {"toggle": True}, "m": {"mute": True},
             "ArrowLeft": {"seek": -5}, "ArrowRight": {"seek": 5}, "j": {"seek": -10}, "l": {"seek": 10},
             "ArrowUp": {"volume": 5}, "ArrowDown": {"volume": -5}}
    assert _run("Object.fromEntries(Object.keys(a).map(k => [k, S.playerKeyAction({ key: k })]))", cases) == cases
    assert _run("['a', 'f', 'c', 'Enter', 'Tab'].map(k => S.playerKeyAction({ key: k }))") == [None] * 5


@needs_node
def test_player_keys_leave_other_shortcuts_and_repeats_alone():
    for mod in ("altKey", "ctrlKey", "metaKey", "isComposing"):          # Alt+C／Alt+B／Ctrl+F… 是別的快捷鍵
        assert _run("S.playerKeyAction({ key: ' ', [a]: true })", mod) is None
    for key in (" ", "k", "m"):                                          # 按住不放：播放暫停與靜音不能一直切換
        assert _run("S.playerKeyAction({ key: a, repeat: true })", key) is None
    assert _run("S.playerKeyAction({ key: 'ArrowRight', repeat: true })") == {"seek": 5}   # 快轉按住會連續


def test_fullscreen_keeps_focus_on_the_page_and_handles_player_keys_itself():
    """YouTube 的快捷鍵要焦點在播放器內部元素上才有用，程式把焦點交給 iframe 沒用（實測 activeElement 已是 IFRAME 仍然無效），
    所以全螢幕時焦點留在頁面上、由我們用播放器 API 處理。"""
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "playerKeyAction(e)" in js and "doPlayerKey(act)" in js
    assert "player.pauseVideo()" in js and "player.playVideo()" in js and "player.seekTo(" in js
    assert "if (inFullscreen()) { document.activeElement?.blur?.(); return; }" in js   # 全螢幕不把焦點塞進 iframe
    assert "debug_log" not in js and "__dbg" not in js                                  # 除錯用的程式碼已移除
