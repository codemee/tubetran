// 全螢幕鈕何時顯示：跟著 YouTube 播放器的控制列。純函式，沒有任何 DOM 依賴，可以用 Node 直接測試。
//
// 最準的做法（桌面版）：直接看 YouTube 控制列右下角的「YouTube」字樣在不在。那個字樣永遠是白色、位置固定，
// 並且和整個控制列一起出現、一起淡出。網頁讀不到跨網域 iframe 的像素，所以由桌面版從螢幕截取那一小塊，
// 回傳「白色像素的比例」（有字樣約 0.36，沒有約 0；實測與頁面截圖逐點一致）。
//
// 偵測不到時（瀏覽器、被我們的字幕蓋住那塊區域、截取失敗）才退回用時間估計。實測 YouTube 在滑鼠停止移動後
// 約 4 秒才收起控制列，所以估計值用 4 秒。
(function (root) {
  const HIDE_MS = 4000;                  // 退回用時間估計時：滑鼠不動／移出後，再顯示多久才隱藏
  const LOGO_MIN = 0.22, LOGO_MAX = 0.60; // 字樣區域的白色比例落在這個範圍才算「字樣在」。
                                          // 上限用來排除整塊都是白的畫面（例如白牆），那不是字樣。

  const logoInRange = (f) => f != null && f >= LOGO_MIN && f <= LOGO_MAX;

  // 防抖：偶發的單次異常值（例如截圖瞬間畫面被重畫）不能讓按鈕閃爍。上一次讀到字樣、這一次沒讀到時，
  // 先當作字樣還在；要連續兩次都讀不到才算消失。
  function fsLogoReading(current, previous) {
    if (current != null && !logoInRange(current) && logoInRange(previous)) return previous;
    return current;
  }

  // state: { inside, lastActivity, leftAt, overButton }
  // logoFraction: 字樣區域的白色比例；偵測不到時是 null
  function fsShouldShow(state, now, paused, canTrackMotion, logoFraction) {
    if (state.overButton) return true;                                   // 滑鼠正在按鈕上，不能在手下消失
    if (logoFraction != null) return logoInRange(logoFraction);
    if (state.inside) {
      if (paused) return true;                        // 暫停時 YouTube 的控制列一直顯示
      if (!canTrackMotion) return true;               // 偵測不到 iframe 內的滑鼠移動：在裡面就一直顯示
      return now - state.lastActivity < HIDE_MS;      // 播放中、滑鼠不動超過一段時間就隱藏
    }
    return now - state.leftAt < HIDE_MS;              // 滑鼠移出後，再顯示一段時間才隱藏
  }

  // 全螢幕快捷鍵 F：什麼情況下才算。在輸入框、下拉選單裡打字（例如網址列、搜尋框、標籤輸入框）時不能搶走；
  // 同時按著 Ctrl／Alt／Meta 是別的快捷鍵（例如 Ctrl+F 搜尋）；按住不放不要一直切換。
  function fsHotkey(e, activeTag) {
    if (!e || (e.key !== "f" && e.key !== "F")) return false;
    if (e.ctrlKey || e.altKey || e.metaKey || e.repeat || e.isComposing) return false;
    return !/^(INPUT|TEXTAREA|SELECT)$/.test(activeTag || "");
  }

  root.fsShouldShow = fsShouldShow;
  root.fsHotkey = fsHotkey;
  root.fsLogoReading = fsLogoReading;
  root.FS_HIDE_MS = HIDE_MS;
  if (typeof module !== "undefined" && module.exports) module.exports = { fsShouldShow, fsLogoReading, fsHotkey, HIDE_MS, LOGO_MIN, LOGO_MAX };
})(typeof window !== "undefined" ? window : globalThis);
