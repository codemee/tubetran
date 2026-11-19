// 字幕高低位置：播放時用 Alt+↑ / Alt+↓ 調整，視窗與全螢幕各記一個位置（YouTube 進度條在兩種畫面的高度不一樣）。
// 純函式，沒有任何 DOM 依賴，可以用 Node 直接測試。
//
// 位置是「字幕底邊離播放區底部多少 CSS 像素」（bottom），null 代表沿用 CSS 預設值（max(30px, 5%)）。
(function (root) {
  const STEP = 4;          // 每按一次移動幾像素（按住不放時系統每秒約重複 30 次，約每秒 120px）
  const MAX_FRACTION = 0.8; // 最高到播放區高度的 80%：再高字幕就跑出畫面了
  const REPEAT_DELAY = 350; // 輪詢模式（桌面版、焦點在影片裡）：按住多久才開始連續移動
  const REPEAT_EVERY = 50;  // 之後每隔多久移動一次

  // 快捷鍵是 Alt+↑ / Alt+↓：YouTube 的音量快捷鍵只認單純的 ↑ ↓，加了 Alt 就不會互相干擾。
  // Alt+方向鍵在輸入框裡沒有別的用途，所以打字時（網址列、搜尋框、書籤名稱）照樣可以調整字幕位置；
  // 只有 Alt+↓ 會展開的元素例外：下拉選單、附建議清單（datalist）的輸入框（標籤輸入框）。
  function claimsAltArrows(el) {
    if (!el) return false;
    if ((el.tagName || "") === "SELECT") return true;
    return (el.tagName || "") === "INPUT" && !!(el.list || (el.getAttribute && el.getAttribute("list")));
  }

  // 這個按鍵事件是不是「調整字幕位置」：回傳 1（Alt+↑，字幕往上）、-1（Alt+↓，字幕往下）、0（不是）。
  // 一定要按著 Alt，而且不能同時按 Ctrl／Meta／Shift（AltGr 會被系統當成 Ctrl+Alt，也就一併排除）；輸入法選字中不算。
  function subKey(e, activeEl) {
    if (!e || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return 0;
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.isComposing) return 0;
    if (claimsAltArrows(activeEl)) return 0;
    return e.key === "ArrowUp" ? 1 : -1;
  }

  // 限制在播放區之內（取整數像素）
  function clampBottom(px, stageHeight) {
    const max = Math.max(0, (Number(stageHeight) || 0) * MAX_FRACTION);
    return Math.round(Math.min(max, Math.max(0, Number(px) || 0)));
  }

  function moveBottom(current, dir, stageHeight) {
    return clampBottom(current + dir * STEP, stageHeight);
  }

  // 輪詢模式（網頁收不到按鍵，改由桌面版回報「現在按著哪個鍵」）：剛按下立刻移動一次，按住超過 REPEAT_DELAY 後
  // 每隔 REPEAT_EVERY 移動一次。state 由呼叫端保存：{ dir, since, last }；放開（dir 為 0）時重置。
  function repeatStep(state, dir, now) {
    if (!dir) { state.dir = 0; return false; }
    if (dir !== state.dir) { state.dir = dir; state.since = state.last = now; return true; }
    if (now - state.since >= REPEAT_DELAY && now - state.last >= REPEAT_EVERY) { state.last = now; return true; }
    return false;
  }

  // 讀取記下來的位置：{ win, fs }，每個是 >= 0 的有限數字或 null；格式不對就當作沒有記過
  function parseStored(raw) {
    const out = { win: null, fs: null };
    try {
      const o = JSON.parse(raw || "{}");
      for (const k of Object.keys(out)) {
        if (typeof o[k] === "number" && Number.isFinite(o[k]) && o[k] >= 0) out[k] = o[k];
      }
    } catch (_) { /* 沒有或壞掉：用預設位置 */ }
    return out;
  }

  const api = { STEP, MAX_FRACTION, REPEAT_DELAY, REPEAT_EVERY, claimsAltArrows, subKey, clampBottom, moveBottom, repeatStep, parseStored };
  root.SubPos = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
