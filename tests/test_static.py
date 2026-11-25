"""前端樣式的版面規則（版面數值是用 Edge 載入真實 YouTube 播放器實測過的）。"""
import re

from tubetran import config


def _css() -> str:
    return (config.STATIC_DIR / "style.css").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"找不到 {selector} 的樣式"
    return m.group(1)


def test_fullscreen_button_is_aligned_with_and_right_of_the_youtube_wordmark():
    """YouTube 控制列右下角的「YouTube」字樣，在任何播放器大小下位置都一樣（用真實播放器實測）：
    右緣離右邊 60px、垂直中心離底部 37px。按鈕 28px：bottom = 37 − 14 = 23px 才會中心對齊；
    新版字樣外有一顆膠囊（右緣離右邊約 28px），按鈕疊在膠囊右端；實際微調後離右邊 18px 最順手 → right = 18px。
    不能放右上角（會蓋住 YouTube 的設定按鈕）。"""
    rule = _rule(_css(), "#fs")
    assert re.search(r"bottom:\s*23px", rule) and re.search(r"right:\s*18px", rule)
    assert "top:" not in rule
    width, height = re.search(r"width:\s*(\d+)px", rule), re.search(r"height:\s*(\d+)px", rule)
    assert width and height and int(width.group(1)) == int(height.group(1)) == 28
    assert 23 + 28 // 2 == 37                                              # 按鈕中心 = 字樣中心


def test_fullscreen_button_matches_youtubes_transparent_white_line_style():
    css = _css()
    rule = _rule(css, "#fs")
    assert re.search(r"background:\s*transparent", rule) and re.search(r"color:\s*#fff", rule)
    svg = _rule(css, "#fs svg")
    assert "fill: none" in svg and "stroke: currentColor" in svg           # 線條圖示，不是填色
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "⛶" not in html                                                 # 不再用字元，改成線條 SVG
    assert re.search(r'id="fs".*?<svg viewBox="0 0 24 24"', html, re.S)


def test_subtitles_sit_low():
    rule = _rule(_css(), "#overlay")
    css = _css()
    assert re.search(r"bottom:\s*var\(--sub-bottom,\s*max\(14px,\s*2%\)\)", rule)             # 控制列收起：貼近下緣；手動調整後用 --sub-bottom
    assert re.search(r"#stage\.active #overlay\s*\{\s*bottom:\s*var\(--sub-bottom,\s*86px\)", css)  # 控制列出現：抬到進度條上方（進度條頂端實測約 76px）
    assert re.search(r"#stage\.slides #overlay\s*\{\s*bottom:\s*var\(--sub-bottom,\s*max\(14px,\s*2%\)\)", css)  # 投影片模式沒有控制列
    assert css.index("#stage.active #overlay") < css.index("#stage.slides #overlay")          # 同樣的權重，投影片的規則要在後面才會蓋過去


def test_transcript_follows_playback_and_can_return_to_current_line():
    """字幕清單跟著播放位置：展開時立刻跳到目前這句；手動捲走時暫停跟隨，提供「回到目前字幕」。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<details id="transcript"[^>]*>.*<button id="follow"[^>]*data-i18n="follow_now"', html, re.S)
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    assert i18n.count("follow_now:") == 2  # 中英文都有
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '$("transcript").addEventListener("toggle"' in js  # 展開時跳到目前這句（回歸：原本一直停在開頭）
    assert "function lastStarted" in js                      # 兩句之間的空檔也維持標示
    assert _rule(_css(), ".row.on small")                    # 正在播放的那句連時間也標出來


def test_slide_mode_hides_youtube_controls_and_steps_through_subtitles():
    """投影片模式：不顯示 YouTube 控制介面（重建播放器時 controls: 0），透明遮罩擋住播放器，
    左右箭頭／← →／PageUp PageDown 跳到上一則、下一則字幕，畫面停在那一格（開始播放就立刻暫停）。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for el in ('id="slide-shield"', 'id="slide-prev"', 'id="slide-next"', 'id="slide-count"', 'id="slide-toggle"'):
        assert el in html
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "controls: 0" in js and "(slideMode || holdFrame)" in js
    # 回歸：開始播放時一定要先套用「隱藏 YouTube 原字幕」，再處理投影片模式的暫停（原本提早 return，原字幕會出現）
    assert js.index("PlayerState.PLAYING) applyNativeCaptions()") < js.index("(slideMode || holdFrame)")
    assert "PageDown" in js and "ArrowRight" in js                    # 簡報遙控器送 PageUp／PageDown
    assert "slideMode || fsShouldShow" in js                          # 沒有 YouTube 控制列可跟：全螢幕鈕一直顯示
    css = _css()
    assert re.search(r"#stage\.slides #slide-shield\s*\{[^}]*inset:\s*0", css)
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("slide_mode:", "slide_mode_tip:", "slide_prev:", "slide_next:", "slide_prev_aria:", "slide_next_aria:"):
        assert i18n.count(key) == 2, key                              # 中英文都有


def test_youtube_captions_always_hidden_and_a_no_subtitles_mode():
    """YouTube 原字幕一律隱藏（不再提供選項）；字幕模式多一個「無」（練聽力），只影響影片上的字幕。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="hide-native"' not in html
    assert 'name="mode" value="none"' in html
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'player.unloadModule("captions")' in js and 'loadModule("captions")' not in js.replace('unloadModule("captions")', "")
    assert 'mode === "none" ? "both"' in js  # 字幕清單仍顯示雙語


def test_library_has_import_and_export():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="lib-import"' in html and 'id="lib-export"' in html and 'type="file"' in html
    # 匯入鈕在 #lib-tools 外面：影片庫是空的時（#lib-tools 隱藏）也要能匯入
    assert html.index('id="lib-import"') < html.index('id="lib-tools"')


def test_export_current_video_sits_with_the_player_toolbar_and_export_all_in_the_library():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bar = html[html.index('id="bar"'):html.index('id="transcript"')]
    assert 'id="export-current"' in bar                    # 匯出目前這支：播放器下方工具列（和下載 SRT／VTT 一起）
    top = html[html.index('id="lib-top"'):html.index('id="lib-tools"')]
    assert 'id="lib-export"' in top and 'id="lib-import"' in top
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert '$("export-current").hidden = !data.complete' in js  # 翻譯完成才能匯出


def test_slide_mode_uses_our_own_captured_images():
    """投影片模式用自己擷取的畫面（沒有 YouTube 的播放介面）蓋住播放器；第一次進入時才請後端準備。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert html.index('id="player"') < html.index('id="slide-img"') < html.index('id="overlay"')  # 蓋住播放器、字幕在上面
    assert 'id="slide-prep"' in html                                    # 準備進度
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function ensureSlides" in js and 'pollSlides(videoId, "POST")' in js
    assert "ensureSlides(); }" in js                                    # 進入投影片模式時才開始準備
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("slides_downloading:", "slides_extracting:", "slides_error:"):
        assert i18n.count(key) == 2, key


def test_hidden_attribute_always_hides():
    """回歸：瀏覽器預設的 [hidden]{display:none} 會被 .btn 的 display: inline-flex 蓋掉，
    「刪除投影片」「下載 SRT／VTT」「匯出」設了 hidden 照樣顯示。要有一條全域規則。"""
    assert re.search(r"(^|\n)\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", _css())


def test_toolbar_right_group_does_not_use_a_spacer_element():
    """回歸：撐開用的空白元素寬度 0 卻多佔一個 gap，寬度剛好時「匯出」被擠到下一行。改用 margin-left:auto。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'class="sp"' not in html
    assert re.search(r"#dl-srt\s*\{\s*margin-left:\s*auto", _css())


def test_toolbar_buttons_are_icons_with_tooltips():
    """工具列的按鈕都是圖示：沒有可見文字（不能用 data-i18n，它會用文字蓋掉圖示），名稱放在 title 與 aria-label。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bar = html[html.index('id="bar"'):html.index('id="transcript"')]
    top = html[html.index('id="lib-top"'):html.index('id="lib-tools"')]
    for area, bid in [(bar, b) for b in ("slide-toggle", "slide-delete", "bm-toggle", "dl-srt", "dl-vtt", "export-current")] + \
                     [(top, b) for b in ("lib-import", "lib-export")]:  # 影片庫上方的匯入／匯出全部也是
        tag = re.search(rf'<(?:button|a) id="{bid}"[^>]*>', area).group(0)
        assert "data-i18n=" not in tag, bid
        assert re.search(r'data-i18n-attr="title:\w+;aria-label:\w+"', tag), bid
        body = area[area.index(tag) + len(tag):].split("</", 1)[0]
        assert "<svg" in body, bid


def test_fullscreen_button_hands_focus_back_to_the_player():
    """回歸：按全螢幕鈕後焦點留在鈕上，← → 快轉倒轉沒有作用。要把焦點交還給播放器（投影片模式只取消焦點）。"""
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    fn = js[js.index("function focusPlayer()"):]
    fn = fn[:fn.index("\n}\n")]
    assert "getIframe" in fn and "frame.focus()" in fn and "slideMode" in fn and "btn.blur()" in fn
    assert 'setTimeout(focusPlayer, 0)' in js


def test_failed_translation_can_be_retried():
    """翻譯失敗時：狀態列下方有「重試」鈕；影片庫的卡片標成失敗、有重試鈕，滑過可看到原因。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert html.index('id="status"') < html.index('id="retry"') < html.index('id="bar"')
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'v.status === "error" || v.status === "paused"' in js and "data-retry=" in js
    assert 'v.status === "error" && v.error' in js  # tooltip 附上失敗原因
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("lib_error:", "retry:", "retry_tip:"):
        assert i18n.count(key) == 2, key


def test_subtitle_search_panel():
    """搜尋字幕：放大鏡在「刪除投影片」旁邊，展開面板有不分大小寫／完整單字／規則表達式、上一個／下一個、
    以及「影片也跳過去」選項；命中的地方在字幕清單中反白。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bar = html[html.index('id="bar"'):html.index('id="transcript"')]
    assert bar.index('id="slide-delete"') < bar.index('id="search-toggle"') < bar.index('id="dl-srt"')
    for el in ("search-panel", "search-q", "search-prev", "search-next", "search-ci", "search-word", "search-re", "search-seek"):
        assert f'id="{el}"' in bar, el
    assert '<script src="/static/search.js">' in html
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "lines(s, listMode(), i)" in js                   # 清單才標示；影片上的字幕不標
    assert '$("search-seek").checked' in js and "player.seekTo(segs[i].start" in js
    assert "searchOpening" in js                             # 搜尋展開清單時停在命中那行，不跳回播放位置
    css = _css()
    assert re.search(r"\.row mark\.cur\s*\{", css)
    assert css.count("--search-cur:") == 3                    # 淺色、深色（系統）、深色（手動）都有
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("search:", "search_ci:", "search_word:", "search_re:", "search_seek:", "search_none:", "search_bad:"):
        assert i18n.count(key) == 2, key


def test_subtitle_bookmarks():
    """書籤：字幕清單每行左側有滑過才浮現的 + 鈕，按下可填名稱加入；搜尋鈕旁有書籤鈕（有書籤才出現），
    展開後列出書籤，點一個跳到對應的字幕。"""
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    bar = html[html.index('id="bar"'):html.index('id="transcript"')]
    assert bar.index('id="search-toggle"') < bar.index('id="bm-wrap"') < bar.index('id="bm-toggle"') < bar.index('id="bm-panel"') < bar.index('id="dl-srt"')
    assert re.search(r'<div id="bm-wrap" hidden>', bar)  # 沒有書籤時不顯示
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "/bookmarks" in js and "gotoBookmark" in js and "bmFor !== videoId" in js
    assert 'class="bm-btn' in js and 'class="bm-edit"' in js
    toolbar_icon = re.search(r'id="bm-toggle".*?(<svg.*?</svg>)', html, re.S).group(1)
    assert f"const BM_ICON = '{toolbar_icon}'" in js     # 清單上的按鈕與工具列的書籤鈕同一個圖示
    list_click = js[js.index('$("list").addEventListener("click"'):]
    list_click = list_click[:list_click.index("\n});\n")]
    assert list_click.index(".bm-btn") < list_click.index("player.seekTo")  # 按 + 鈕、輸入框不會跳播
    assert 'class="bm-x"' in js and 'e.target.closest(".bm-x")' in js  # 書籤清單的項目有滑過才浮現的刪除鈕
    css = _css()
    assert re.search(r"\.bm-x\s*\{[^}]*opacity:\s*0", css) and re.search(r"\.bm-row:hover \.bm-x", css)
    assert re.search(r"\.bm-btn\s*\{[^}]*opacity:\s*0", css) and re.search(r"\.row:hover \.bm-btn", css)
    assert re.search(r"\.bm-btn\s*\{[^}]*left:\s*\d+px", css)  # 浮在左側
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("bm:", "bm_tip:", "bm_add:", "bm_edit:", "bm_ph:", "bm_ok:", "bm_cancel:", "bm_del:"):
        assert i18n.count(key) == 2, key


def test_untranslated_traditional_lines_are_shown_once():
    """原文本來就是繁體中文（不需翻譯、譯文與原文相同）：雙語模式與搜尋都只算一次，不重複顯示同一句。"""
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 's.trans === s.text && m === "both"' in js
    assert "s.trans !== s.text" in js


def test_switching_videos_leaves_slide_mode():
    """在投影片模式中切到其他影片（或刪除、重新處理目前這支）要退出投影片模式，新影片用正常的播放器。"""
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    reset = js[js.index("function resetView()"):]
    reset = reset[:reset.index("\n}\n")]
    assert "slideMode = false" in reset and 'classList.remove("slides")' in reset
    assert "player = null" in reset  # 沒有控制列、靜音的播放器拆掉，下一支影片重新建立正常的播放器

def test_all_confirmations_use_the_custom_dialog_not_the_builtin_confirm():
    """所有確認（刪除、重新處理、重新翻譯、重設術語表、刪除投影片、放棄未儲存的修改）都用自製對話框 appConfirm，
    外觀才會跟應用程式一致；不能再有內建的 confirm()。"""
    import re

    for name in ("app.js", "glossary.js", "settings.js", "desktop.js", "search.js"):
        js = (config.STATIC_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"(?<![A-Za-z.])confirm\(", js), f"{name} 還在用內建的 confirm()"
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("modal_ok", "modal_cancel", "modal_delete", "modal_redo", "modal_retrans", "modal_reset", "modal_cancel_job", "modal_keep_job", "modal_discard", "modal_keep"):
        assert i18n.count(f"{key}:") == 2, key                                  # 中文、英文各一
