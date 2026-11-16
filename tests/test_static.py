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
    和字樣空 8px → 左緣離右邊 52px → right = 52 − 28 = 24px。不能放右上角（會蓋住 YouTube 的設定按鈕）。"""
    rule = _rule(_css(), "#fs")
    assert re.search(r"bottom:\s*23px", rule) and re.search(r"right:\s*24px", rule)
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
    assert re.search(r"bottom:\s*max\(30px,\s*5%\)", rule)        # 視窗化至少 30px，全螢幕約 5%


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
