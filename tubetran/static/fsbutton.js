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

  // 字幕模式快捷鍵 Alt+C：用 Alt 組合鍵是為了不和 YouTube 自己的 C（開關字幕）衝突，YouTube 的快捷鍵都不處理 Alt 組合。
  // 一定要按著 Alt，且不能同時按 Ctrl／Meta／Shift（AltGr 會被系統當成 Ctrl+Alt，一併排除）；按住不放、輸入法選字中不算。
  // macOS 的 Option+C 會產生 "ç"，所以也認實體按鍵 code。Alt+C 在輸入框裡沒有別的用途，打字時也能用。
  function altHotkey(e, letter) {
    if (!e || !(String(e.key).toLowerCase() === letter || e.code === "Key" + letter.toUpperCase())) return false;
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat || e.isComposing) return false;
    return true;
  }
  const captionHotkey = (e) => altHotkey(e, "c");
  // 書籤清單快捷鍵 Alt+B（同樣的條件；YouTube 沒有 Alt 組合的快捷鍵）
  const bookmarkHotkey = (e) => altHotkey(e, "b");

  // 字幕模式的循環順序：雙語 → 原文 → 譯文 → 無字幕 → 雙語
  const CAPTION_MODES = ["both", "orig", "trans", "none"];
  const nextCaptionMode = (m) => CAPTION_MODES[(CAPTION_MODES.indexOf(m) + 1) % CAPTION_MODES.length];
  // 讀取記下來的模式；沒有或不認得就用雙語
  const parseCaptionMode = (raw) => (CAPTION_MODES.includes(raw) ? raw : "both");

  // 全螢幕時由我們自己處理的 YouTube 播放器快捷鍵（Space／K 播放暫停、← → 5 秒、J L 10 秒、M 靜音、↑ ↓ 音量）。
  // 原因：YouTube 的快捷鍵要焦點在播放器「內部」的元素上才有用，用程式把焦點交給 iframe 沒有用（只有使用者真的點過影片才有），
  // 所以全螢幕時焦點留在我們的頁面上，由我們用播放器 API 做同樣的事；使用者點過影片後焦點在 iframe 裡，則由 YouTube 原生處理。
  // 傳回要做的事，不是快捷鍵就傳回 null。Alt／Ctrl／Meta 組合是別的快捷鍵（Alt+C、Alt+B、Ctrl+F…）；按住不放時只有連續動作會重複。
  function playerKeyAction(e) {
    if (!e || e.altKey || e.ctrlKey || e.metaKey || e.isComposing) return null;
    switch (e.key) {
      case " ": case "k": case "K": return e.repeat ? null : { toggle: true };
      case "m": case "M": return e.repeat ? null : { mute: true };
      case "ArrowLeft": return { seek: -5 };
      case "ArrowRight": return { seek: 5 };
      case "j": case "J": return { seek: -10 };
      case "l": case "L": return { seek: 10 };
      case "ArrowUp": return { volume: 5 };
      case "ArrowDown": return { volume: -5 };
      default: return null;
    }
  }

  // 啟動時載入上次看的影片：設定記在這台電腦上，預設開啟（只有明確存了 "0" 才是關閉）
  const resumeLastEnabled = (raw) => raw !== "0";
  // 該載入哪一支：記下的影片 ID 格式要對、而且還在影片庫裡、已處理完成（status 是 done）。
  // 處理到一半或失敗的不自動開，因為開啟影片會（重新）啟動處理，不能在使用者沒操作時花翻譯費用。
  function pickResumeVideo(id, library) {
    if (typeof id !== "string" || !/^[A-Za-z0-9_-]{11}$/.test(id)) return null;
    const v = (Array.isArray(library) ? library : []).find((x) => x && x.video_id === id);
    return v && v.status === "done" ? id : null;
  }

  root.resumeLastEnabled = resumeLastEnabled;
  root.pickResumeVideo = pickResumeVideo;
  root.playerKeyAction = playerKeyAction;
  root.fsShouldShow = fsShouldShow;
  root.fsHotkey = fsHotkey;
  root.fsLogoReading = fsLogoReading;
  root.captionHotkey = captionHotkey;
  root.bookmarkHotkey = bookmarkHotkey;
  root.nextCaptionMode = nextCaptionMode;
  root.parseCaptionMode = parseCaptionMode;
  root.FS_HIDE_MS = HIDE_MS;
  if (typeof module !== "undefined" && module.exports) module.exports = { fsShouldShow, fsLogoReading, fsHotkey, captionHotkey, bookmarkHotkey, playerKeyAction, resumeLastEnabled, pickResumeVideo, nextCaptionMode, parseCaptionMode, CAPTION_MODES, HIDE_MS, LOGO_MIN, LOGO_MAX };
})(typeof window !== "undefined" ? window : globalThis);
