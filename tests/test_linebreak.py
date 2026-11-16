"""影片上的字幕怎麼折行（static/linebreak.js）。純函式，用 Node 直接執行測試。

寬度用簡化的量法：英數字與空白算 1，其他（中文、全形標點）算 2，大致等於畫面上的比例。"""
import json
import shutil
import subprocess

import pytest

from tubetran import config

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def split(text: str, max_width: float) -> list[str]:
    script = (
        "const { splitLines } = require(process.argv[1]);"
        "const [text, max] = JSON.parse(process.argv[2]);"
        "const w = (s) => [...s].reduce((n, c) => n + (/[\\x00-\\x7f]/.test(c) ? 1 : 2), 0);"
        "console.log(JSON.stringify(splitLines(text, max, w)));"
    )
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "linebreak.js"), json.dumps([text, max_width])],
                         capture_output=True, text=True, check=True, timeout=30, encoding="utf-8")
    return json.loads(out.stdout)


def width(s: str) -> int:
    return sum(1 if ord(c) < 128 else 2 for c in s)


def test_short_line_is_left_alone():
    assert split("Same ideas.", 40) == ["Same ideas."]
    assert split("其實是同樣的概念。", 40) == ["其實是同樣的概念。"]


def test_no_tiny_second_line():
    """回歸：瀏覽器塞滿第一行，第二行只剩一兩個字。兩行要差不多長。"""
    zh = "當容器內的 root 不是主機上真正的 root，那就是使用者命名空間的對應機制。懂了吧？"
    lines = split(zh, width(zh) - 6)  # 只差一點點放不下
    assert len(lines) == 2 and "".join(lines).replace(" ", "") == zh.replace(" ", "")
    a, b = (width(x) for x in lines)
    assert min(a, b) >= 0.3 * (a + b)


def test_prefers_breaking_after_punctuation():
    zh = "當 Docker 提到磁碟區掛載，就是小心地讓不同的掛載視角共享同一個資料夾。"
    assert split(zh, 50) == ["當 Docker 提到磁碟區掛載，", "就是小心地讓不同的掛載視角共享同一個資料夾。"]
    en = "When Docker says volume mount, that is carefully sharing a folder across mount views."
    assert split(en, 60) == ["When Docker says volume mount,", "that is carefully sharing a folder across mount views."]


def test_never_splits_an_english_word_or_starts_a_line_with_punctuation():
    zh = "大量使用ContainerRuntimeInterface來管理機器上的服務，就算完全沒有用到也一樣"
    for max_w in range(30, 80, 3):
        lines = split(zh, max_w)
        assert "ContainerRuntimeInterface" in "".join(f"|{x}|" for x in lines)  # 單字完整留在同一行
        assert not any(x[0] in "，。、！？" for x in lines)


def test_very_long_text_uses_more_lines_each_fitting():
    en = " ".join(["word"] * 60)  # 299 個字元
    lines = split(en, 80)
    assert len(lines) == 4 and all(width(x) <= 80 for x in lines)
    assert " ".join(lines) == en
