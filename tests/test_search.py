"""字幕搜尋的比對邏輯（static/search.js）。純函式，用 Node 直接執行測試。"""
import json
import shutil
import subprocess

import pytest

from tubetran import config

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def _node(expr: str, *args):
    script = (
        "const S = require(process.argv[1]);"
        "const a = JSON.parse(process.argv[2]);"
        f"console.log(JSON.stringify({expr}));"
    )
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "search.js"), json.dumps(args)],
                         capture_output=True, text=True, check=True, timeout=30, encoding="utf-8")
    return json.loads(out.stdout)


def find(text: str, query: str, **opts) -> list[list[int]]:
    """回傳命中的子字串（比範圍好讀）；規則寫錯回傳 {"error": ...}。"""
    return _node(
        "(() => { const b = S.buildSearch(a[1], a[2]); if (!b) return null; if (b.error) return {error: b.error};"
        " return S.findRanges(a[0], b.re).map(([s, e]) => a[0].slice(s, e)); })()",
        text, query, opts)


def test_plain_text_is_literal_and_case_option_works():
    assert find("Docker and docker", "docker", ignoreCase=True) == ["Docker", "docker"]
    assert find("Docker and docker", "docker") == ["docker"]                  # 分大小寫
    assert find("a.b axb", "a.b") == ["a.b"]                                   # 不是規則表達式時，. 是字面上的點
    assert find("anything", "") is None                                        # 空字串：不搜尋


def test_whole_word_for_english_but_not_blocking_chinese():
    assert find("cat catalog bobcat cat.", "cat", wholeWord=True) == ["cat", "cat"]
    assert find("Café cafés", "café", wholeWord=True, ignoreCase=True) == ["Café"]
    # 中文沒有空白分詞：「完整單字」不能讓中文永遠找不到
    assert find("Docker 容器化與容器", "容器", wholeWord=True) == ["容器", "容器"]


def test_regular_expression_and_errors():
    assert find("v1.2 and v10.3", r"v\d+\.\d", regex=True) == ["v1.2", "v10.3"]
    assert find("cat dog", "cat|dog", regex=True, wholeWord=True) == ["cat", "dog"]
    assert "error" in find("abc", "a(", regex=True)
    assert find("aaa", "x*", regex=True) == []                                  # 長度 0 的命中略過、不會無窮迴圈
    assert find("😀a😀", "a*", regex=True) == ["a"]                            # 跨過 surrogate pair 也不會卡住


def test_highlight_wraps_matches_and_escapes_the_rest():
    html = _node(
        "S.highlight(a[0], S.findRanges(a[0], S.buildSearch('b', {}).re),"
        " (s) => s.replace(/</g, '&lt;'), (k) => ` data-m=\"${k}\"`)",
        "<a>b<c>b")
    assert html == '&lt;a>' + '<mark data-m="0">b</mark>' + '&lt;c>' + '<mark data-m="1">b</mark>'
