// 桌面版（pywebview，Windows／Linux 無框視窗）：自製視窗按鈕、拖曳區域、邊緣縮放。
// 在瀏覽器（伺服器模式）裡沒有 window.pywebview，這個檔案什麼都不會做。
// 依賴 app.js 的 $、saveProgress 與 i18n.js 的 t()。
(function () {
  const root = document.documentElement;
  const topbar = document.querySelector(".topbar");
  const maxBtn = $("win-max");
  let api = null;
  let maximized = false;

  function paint() {
    root.classList.toggle("maxed", maximized);
    maxBtn.dataset.state = maximized ? "restore" : "max";
    maxBtn.title = t(maximized ? "win_restore" : "win_max");
    maxBtn.setAttribute("aria-label", maxBtn.title);
    // 最大化時不能拖曳移動（雙擊空白處或按還原鈕回到原本大小）
    // 頁首空白處與左上角的圖示都能拖曳（pywebview 只認「直接點到」帶這個 class 的元素，裡面的輸入框與按鈕不受影響）。
    // 最大化時不能拖曳移動（雙擊空白處或按還原鈕回到原本大小）
    topbar.classList.toggle("pywebview-drag-region", !maximized);
    document.querySelector(".brand").classList.toggle("pywebview-drag-region", !maximized);
    $("resize-handles").hidden = maximized;
  }

  async function toggleMax() {
    try {
      const s = await api.window_toggle_maximize();
      maximized = !!s.maximized;
      paint();
    } catch (_) {}
  }

  function setupResize() {
    for (const h of $("resize-handles").children) {
      h.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const edge = h.dataset.edge, k = window.devicePixelRatio || 1;
        const sx = e.screenX, sy = e.screenY;
        let seq = 0, pending = null, raf = 0;
        h.setPointerCapture(e.pointerId);
        api.resize_begin(edge, k);
        // 每個畫面更新只送一次最新的位移（螢幕座標 × 縮放比例 = 實體像素），避免橋接被淹沒
        const send = () => {
          raf = 0;
          if (pending) { api.resize_to(edge, pending.dx, pending.dy, ++seq); pending = null; }
        };
        const move = (ev) => {
          pending = { dx: Math.round((ev.screenX - sx) * k), dy: Math.round((ev.screenY - sy) * k) };
          if (!raf) raf = requestAnimationFrame(send);
        };
        const up = (ev) => {
          h.removeEventListener("pointermove", move);
          h.removeEventListener("pointerup", up);
          h.removeEventListener("pointercancel", up);
          move(ev); send();
          api.resize_end();
        };
        h.addEventListener("pointermove", move);
        h.addEventListener("pointerup", up);
        h.addEventListener("pointercancel", up);
      });
    }
  }

  // 拖曳視窗本身由 pywebview 處理（頁首的 .pywebview-drag-region）。這裡只負責「通知系統」：
  // 真的開始移動（超過幾個像素）時廣播「視窗開始被移動」，放開時廣播「結束」。FancyZones 靠這兩個事件才會
  // 在 Shift 拖曳時顯示區域，並在放開時把視窗吸進去、套用區域的大小。單純點一下不算拖曳，不會廣播。
  function setupDrag() {
    let down = null, begun = false;
    topbar.addEventListener("mousedown", (e) => {
      if (e.button !== 0 || maximized || !(e.target === topbar || e.target.classList.contains("brand"))) return;
      down = { x: e.screenX, y: e.screenY }; begun = false;
    });
    window.addEventListener("mousemove", (e) => {
      if (!down || begun) return;
      if (Math.abs(e.screenX - down.x) + Math.abs(e.screenY - down.y) >= 4) { begun = true; api.window_move_begin(); }
    });
    const finish = () => { if (begun) api.window_move_end(); down = null; begun = false; };
    window.addEventListener("mouseup", finish);
    window.addEventListener("blur", finish);
  }

  async function init() {
    if (api) return;
    api = window.pywebview && window.pywebview.api;
    if (!api || !api.window_state) { api = null; return; }
    let s;
    try { s = await api.window_state(); } catch (_) { api = null; return; }
    if (!s.custom) return; // 使用系統標題列：不需要自製按鈕
    root.classList.add("custom-chrome");
    $("win-ctrls").hidden = false;
    maximized = !!s.maximized;
    paint();
    setupResize();
    $("win-min").addEventListener("click", () => api.window_minimize());
    maxBtn.addEventListener("click", toggleMax);
    $("win-close").addEventListener("click", () => {
      try { saveProgress(); } catch (_) {}      // 先記下播放進度
      setTimeout(() => api.window_close(), 120); // 讓進度的請求有時間送出
    });
    topbar.addEventListener("dblclick", (e) => {
      if (e.target === topbar || e.target.classList.contains("brand")) toggleMax();
    });
    setupDrag();
    window.repaintDesktop = paint; // 切換介面語言時更新按鈕提示
    // 視窗大小被外部改變（視窗管理程式、貼齊等）時，重新向後端確認是否仍是最大化，讓按鈕與縮放把手跟著對
    let t = 0;
    window.addEventListener("resize", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        try { const st = await api.window_state(); if (!!st.maximized !== maximized) { maximized = !!st.maximized; paint(); } } catch (_) {}
      }, 150);
    });
  }

  if (window.pywebview && window.pywebview.api) init();
  else window.addEventListener("pywebviewready", init);
})();
