"""啟動時載入上次看的影片（static/fsbutton.js 的 pickResumeVideo／resumeLastEnabled，加上 app.js 與設定面板的接線）。"""
import json
import shutil
import subprocess

import pytest

from tubetran import config

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 Node.js 來執行前端邏輯")


def _run(expr: str, arg=None):
    script = f"const S = require(process.argv[1]); const a = JSON.parse(process.argv[2]); console.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE, "-e", script, str(config.STATIC_DIR / "fsbutton.js"), json.dumps(arg)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


LIB = [{"video_id": "hO-i1l8BecM", "status": "done"}, {"video_id": "abcdefghijk", "status": "running"},
       {"video_id": "zzzzzzzzzzz", "status": "error"}]


@needs_node
def test_only_a_finished_video_still_in_the_library_is_resumed():
    """開啟影片會（重新）啟動處理、可能花翻譯費用：處理中、失敗、已被刪除的影片，不能在使用者沒操作時自動開。"""
    assert _run("S.pickResumeVideo('hO-i1l8BecM', a)", LIB) == "hO-i1l8BecM"
    for vid in ("abcdefghijk", "zzzzzzzzzzz", "notinlibrary"):
        assert _run("S.pickResumeVideo(a[0], a[1])", [vid, LIB]) is None, vid


@needs_node
def test_stored_video_id_is_validated_before_use():
    for bad in (None, "", "short", "hO-i1l8BecM/../x", "<script>alert(1)</script>", 12345678901):
        assert _run("S.pickResumeVideo(a, [{ video_id: 'hO-i1l8BecM', status: 'done' }])", bad) is None, bad
    assert _run("S.pickResumeVideo('hO-i1l8BecM', a)", None) is None          # 影片庫還沒載入／壞掉
    assert _run("S.pickResumeVideo('hO-i1l8BecM', [null, {}])") is None


@needs_node
def test_resuming_is_on_unless_explicitly_turned_off():
    assert _run("[null, '1', '', 'x'].map(S.resumeLastEnabled)") == [True] * 4   # 預設開啟
    assert _run("S.resumeLastEnabled('0')") is False


def test_page_records_the_last_video_and_loads_it_without_autoplay():
    js = (config.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'localStorage.setItem(LAST_KEY, id)' in js                          # 開啟影片時記下
    assert "loadLibrary().then(openLastVideo)" in js                           # 影片庫載入後才決定要不要開
    assert "if (videoId || runId || !window.getResumeLast()) return;" in js    # 使用者已自己開影片、或關閉了功能：不動
    assert "openUrl(id, { cue: true })" in js and "player.cueVideoById" in js  # 只載入、停在位置，不自動播放
    assert "t(opts.cue ? \"resume_cued\" : \"resume_note\"" in js


def test_settings_panel_has_the_switch_and_it_applies_immediately():
    html = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="set-resume"' in html and html.index('id="set-resume"') < html.index('class="set-actions"')
    st = (config.STATIC_DIR / "settings.js").read_text(encoding="utf-8")
    assert "window.setResumeLast(resumeBox.checked)" in st                     # 切換就生效，不需按「儲存」
    i18n = (config.STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
    for key in ("set_resume:", "set_resume_hint:", "resume_cued:"):
        assert i18n.count(key) == 2, key                                       # 繁中與英文各一
