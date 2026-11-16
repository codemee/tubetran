const $ = (id) => document.getElementById(id);
let player, segs = [], current = -1, mode = "both", videoId = null, runId = 0, partialShown = false;
let lastJob = null;

// 載入 YouTube IFrame API
const tag = document.createElement("script");
tag.src = "https://www.youtube.com/iframe_api";
document.head.appendChild(tag);
const apiReady = new Promise((r) => (window.onYouTubeIframeAPIReady = r));

// 狀態列：src 可以是字串，或「回傳字串的函式」（切換語系時會重新呼叫以重新翻譯）
let statusSrc = "", statusErr = false;
function renderStatus() {
  $("status").textContent = typeof statusSrc === "function" ? statusSrc() : statusSrc;
  $("status").className = statusErr ? "err" : "";
}
function setStatus(src, err = false) { statusSrc = src; statusErr = err; renderStatus(); }

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const viaLabel = (v) => ({ manual: t("via_manual"), auto: t("via_auto"), whisper: t("via_whisper") }[v] || "");
const stageLabel = (s) => (I18N["zh-TW"]["stage_" + s] ? t("stage_" + s) : s);

// ── 捲軸寬度 ──
// 捲動區出現捲軸時，內容區會變窄；窄螢幕時頂欄的網址列要和內容區（播放區）的右緣對齊，所以把捲軸寬度量出來
// 放在 CSS 變數 --sbw（沒有捲軸或是覆蓋式捲軸就是 0）。內容區的寬度會隨捲軸出現／消失而變，ResizeObserver 會通知。
{
  const ps = document.querySelector(".page-scroll");
  const syncScrollbarWidth = () =>
    document.documentElement.style.setProperty("--sbw", `${ps.offsetWidth - ps.clientWidth}px`);
  syncScrollbarWidth();
  if (window.ResizeObserver) new ResizeObserver(syncScrollbarWidth).observe(ps);
}

// ── 主題 ──
// 三種模式：auto（預設，跟隨系統）／light／dark。auto 時不設定 data-theme，交給 CSS 的 prefers-color-scheme
const root = document.documentElement;
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
function getTheme() {
  try { const v = localStorage.getItem("theme"); return v === "light" || v === "dark" ? v : "auto"; }
  catch (_) { return "auto"; }
}
// 分頁圖示（icon）依「實際生效的主題」切換淺色／深色版
function updateFavicon() {
  const th = getTheme(), dark = th === "dark" || (th === "auto" && darkMQ.matches);
  $("favicon").href = `/static/logo/${dark ? "tubetran-dark-icon.svg" : "tubetran-light-icon.svg"}`;
}
function setTheme(v) {
  if (v === "auto") root.removeAttribute("data-theme"); else root.dataset.theme = v;
  try { v === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", v); } catch (_) {}
  updateFavicon();
  paintCtrls();
}
darkMQ.addEventListener("change", updateFavicon);

// 三態按鈕：每按一下切換到下一個狀態（自動 → 淺色 → 深色 → 自動）
const nextOf = (order, cur) => order[(order.indexOf(cur) + 1) % order.length];
$("theme-btn").addEventListener("click", () => setTheme(nextOf(["auto", "light", "dark"], getTheme())));

// 依目前狀態顯示對應圖示（由 CSS 依 data-state 處理），並更新提示文字
function paintCtrls() {
  const th = getTheme(), lg = getLangPref();
  const tb = $("theme-btn"), lb = $("lang-btn");
  tb.dataset.state = th;
  lb.dataset.state = lg;
  const themeState = { auto: t("theme_auto_t"), light: t("theme_light_t"), dark: t("theme_dark_t") }[th];
  const langState = { auto: t("lang_auto_t"), "zh-TW": t("lang_zh_t"), en: t("lang_en_t") }[lg];
  const tt = t("ctrl_title", { label: t("theme_label"), state: themeState });
  const lt = t("ctrl_title", { label: t("lang_label"), state: langState });
  tb.title = tb.ariaLabel = tt;
  lb.title = lb.ariaLabel = lt;
}

// ── 語系 ──
// auto（預設）跟隨瀏覽器語言：中文 → 繁體中文，其他 → English。切換時一併替換對應語系的標誌圖（由 CSS 依 data-lang 處理）
function onLangChange() {
  applyStaticI18n();
  paintCtrls();
  renderStatus();
  if (segs.length) renderList();
  libKey = ""; // 強制重畫影片庫，讓文字換成新語系
  renderLibrary();
  if (lastJob && !$("progress").hidden) showProgress(lastJob);
  window.repaintSettings?.();
  window.repaintDesktop?.();
}
// 三態按鈕：自動（跟隨系統語言）→ 繁體中文 → English → 自動
$("lang-btn").addEventListener("click", () => {
  setLangPref(nextOf(["auto", "zh-TW", "en"], getLangPref()));
  onLangChange();
});

// ── 字幕顯示 ──
// 翻譯進行中時，尚未翻好的句子沒有 trans：先顯示原文，譯文處標示「翻譯中…」
function lines(s) {
  const o = `<div>${esc(s.text)}</div>`;
  const has = s.trans != null;
  const tr = has ? `<div class="t">${esc(s.trans)}</div>` : `<div class="t pending">${t("pending_tr")}</div>`;
  if (mode === "orig") return o;
  if (mode === "trans") return has ? tr : `<div class="pending">${esc(s.text)}</div>`;
  return o + tr;
}

function renderList() {
  const box = $("list"), top = box.scrollTop; // 部分字幕持續更新時，保留清單的捲動位置
  box.innerHTML = segs
    .map((s, i) => `<div class="row" data-i="${i}"><small>${fmt(s.start)}</small>${lines(s)}</div>`)
    .join("");
  box.scrollTop = top;
  const n = segs.filter((s) => s.trans != null).length;
  $("transcript-title").textContent = n < segs.length
    ? t("tx_title_partial", { n, total: segs.length }) : t("tx_title", { total: segs.length });
  current = -1;
  $("overlay").innerHTML = "";
  tick(); // 立刻補回目前這一句，避免更新時字幕閃一下
  if (videoId) {
    $("dl-srt").href = `/api/subtitles/${videoId}.srt?mode=${mode}`;
    $("dl-vtt").href = `/api/subtitles/${videoId}.vtt?mode=${mode}`;
  }
}

$("list").addEventListener("click", (e) => {
  const row = e.target.closest(".row");
  if (row && player) player.seekTo(segs[+row.dataset.i].start, true);
});

document.querySelectorAll("input[name=mode]").forEach((r) =>
  r.addEventListener("change", () => { mode = r.value; renderList(); })
);

function tick() {
  if (!player || !player.getCurrentTime || !segs.length) return;
  const pos = player.getCurrentTime();
  const i = segs.findIndex((s) => pos >= s.start && pos < s.end);
  if (i === current) return;
  current = i;
  document.querySelector(".row.on")?.classList.remove("on");
  if (i < 0) { $("overlay").innerHTML = ""; return; }
  const row = document.querySelector(`.row[data-i="${i}"]`);
  row?.classList.add("on");
  // 只在清單展開時，於清單容器內捲動（不要捲動整個頁面）
  if (row && $("transcript").open) {
    const box = $("list");
    box.scrollTo({ top: row.offsetTop - box.clientHeight / 2 + row.clientHeight / 2, behavior: "smooth" });
  }
  $("overlay").innerHTML = lines(segs[i]);
}
setInterval(tick, 200);

// ── 全螢幕：讓「播放器＋字幕層」整個容器全螢幕（YouTube 原生全螢幕只會全螢幕 iframe）──
// 有些環境（macOS 的 WKWebView）沒有元素全螢幕功能，requestFullscreen 不存在或被拒絕；
// 桌面版這時改成「播放區用 CSS 鋪滿頁面（pseudo-fs）＋整個視窗全螢幕」。
let pseudoFs = false;
function setPseudoFs(on) {
  pseudoFs = on;
  $("stage").classList.toggle("pseudo-fs", on);
  try { window.pywebview?.api?.set_fullscreen(on); } catch (_) {}
  document.dispatchEvent(new Event("fullscreenchange"));
}
// 桌面版在使用者用系統方式退出視窗全螢幕時呼叫（視窗已經退出了，只需收回播放區的鋪滿樣式）
window.__tubetranExitFs = () => {
  if (!pseudoFs) return;
  pseudoFs = false;
  $("stage").classList.remove("pseudo-fs");
  document.dispatchEvent(new Event("fullscreenchange"));
};
function toggleFullscreen() {
  const stage = $("stage");
  const canPseudo = typeof window.pywebview?.api?.set_fullscreen === "function";
  if (document.fullscreenElement) document.exitFullscreen();
  else if (pseudoFs) setPseudoFs(false);
  else if (stage.requestFullscreen) {
    const r = stage.requestFullscreen();
    if (r?.catch) r.catch(() => { if (canPseudo) setPseudoFs(true); });
  } else if (canPseudo) setPseudoFs(true);
}
$("fs").addEventListener("click", toggleFullscreen);
// 桌面版（pywebview）：網頁全螢幕只會填滿視窗內容，要同步讓整個視窗全螢幕。瀏覽器裡沒有這個橋接，什麼都不會做
document.addEventListener("fullscreenchange", () => {
  if (!pseudoFs) { try { window.pywebview?.api?.set_fullscreen(!!document.fullscreenElement); } catch (_) {} }
});
document.addEventListener("keydown", (e) => {
  if (fsHotkey(e, document.activeElement?.tagName)) toggleFullscreen();
});
// 桌面版：點過影片後鍵盤焦點在 YouTube 的 iframe 裡，網頁收不到按鍵（跨網域 iframe 的限制），上面的 keydown 不會觸發。
// 這時改由 Python 讀 F 鍵的狀態（只在我們的視窗在最前面時才會回報按下）。瀏覽器做不到，點過影片後要先點一下影片外面。
{
  let prev = false, busy = false;
  setInterval(async () => {
    if (busy || document.activeElement?.tagName !== "IFRAME" || typeof window.pywebview?.api?.fullscreen_key_down !== "function") { prev = false; return; }
    busy = true;
    try {
      const down = await window.pywebview.api.fullscreen_key_down();
      if (down && !prev) toggleFullscreen();                        // 只在「剛按下」的那一刻切換，按住不放不會一直切換
      prev = down;
    } catch (_) { prev = false; } finally { busy = false; }
  }, 60);
}
// ── 全螢幕鈕的顯示／隱藏（邏輯在 fsbutton.js）──
// 跟著 YouTube 控制列：桌面版直接看控制列右下角的「YouTube」字樣在不在（從螢幕截取那一小塊，算白色像素比例），
// 它和控制列一起出現、一起淡出，所以不必猜時間。偵測不到時（瀏覽器、字幕蓋住那塊區域、截取失敗）才退回用時間估計：
// 桌面版讀系統游標位置判斷滑鼠有沒有動，瀏覽器則「滑鼠在播放區裡就一直顯示」。
{
  const stage = $("stage");
  const fsBtn = $("fs");
  const st = { inside: false, lastActivity: 0, leftAt: -1e9, overButton: false };
  const api = () => window.pywebview?.api;
  let tracking = false, lastCursor = null, cursorBusy = false;
  let logo = { prev: null, value: null, at: -1e9 }, logoBusy = false;
  const activity = () => { st.lastActivity = performance.now(); };
  stage.addEventListener("mousemove", activity);                 // 滑鼠在我們自己的元素上移動（例如那顆鈕）
  document.addEventListener("fullscreenchange", () => { activity(); st.leftAt = performance.now(); }); // 進出全螢幕時先顯示一下

  // YouTube 字樣的位置（CSS 像素，量過 6 種播放器大小、視窗化與全螢幕都一樣）：
  // 右緣離播放區右邊 59～60、垂直中心離底部 36～37、約 80x16。多取一點邊：右緣 57、寬 86、高 22。
  function logoRegion() {
    const r = stage.getBoundingClientRect();
    const right = r.right - 57, cy = r.bottom - 37;
    return { left: right - 86, top: cy - 11, width: 86, height: 22 };
  }
  // 我們自己的字幕若蓋住那塊區域，截到的是字幕不是 YouTube 的字樣，這時不能用偵測結果
  function subtitleCoversLogo(reg) {
    for (const d of document.querySelectorAll("#overlay div")) {
      const b = d.getBoundingClientRect();
      if (b.width && b.height && b.left < reg.left + reg.width && b.right > reg.left && b.top < reg.top + reg.height && b.bottom > reg.top) return true;
    }
    return false;
  }

  async function pollCursor() {
    if (cursorBusy) return;
    cursorBusy = true;
    try {
      const p = await api().cursor_pos();
      tracking = Array.isArray(p);
      if (tracking && (!lastCursor || p[0] !== lastCursor[0] || p[1] !== lastCursor[1])) activity();
      if (tracking) lastCursor = p;
    } catch (_) { tracking = false; } finally { cursorBusy = false; }
  }
  async function pollLogo(reg) {
    if (logoBusy) return;
    logoBusy = true;
    try {
      const f = await api().logo_fraction(reg.left, reg.top, reg.width, reg.height, window.devicePixelRatio || 1);
      logo = { prev: logo.value, value: typeof f === "number" ? f : null, at: performance.now() };
    } catch (_) { logo = { prev: null, value: null, at: -1e9 }; } finally { logoBusy = false; }
  }

  setInterval(() => {
    const now = performance.now();
    const inside = stage.matches(":hover");
    if (inside && !st.inside) st.lastActivity = now;
    if (!inside && st.inside) st.leftAt = now;
    st.inside = inside;
    st.overButton = fsBtn.matches(":hover");
    const hasVideo = $("empty").hidden;                         // 已經有影片（沒有影片時舞台上只有「貼上網址」的提示）
    if (inside && typeof api()?.cursor_pos === "function") pollCursor(); else lastCursor = null;
    // 桌面版：看 YouTube 字樣在不在
    const reg = logoRegion();
    const covered = subtitleCoversLogo(reg);
    if (hasVideo && !covered && typeof api()?.logo_fraction === "function") pollLogo(reg);
    const logoFresh = hasVideo && !covered && now - logo.at < 700;
    const state = player?.getPlayerState?.();                    // player 是本檔案最上面用 let 宣告的，不在 window 上
    const paused = !(state === 1 || state === 3);                // 1 = 播放中、3 = 緩衝中；其餘（暫停、結束、尚未開始）都視為暫停
    const reading = logoFresh ? fsLogoReading(logo.value, logo.prev) : null;   // 防抖：單次異常值不算
    stage.classList.toggle("active", fsShouldShow(st, now, paused, tracking, reading));
  }, 150);
}

// ── YouTube 播放器 ──
// 關閉原生字幕（unloadModule 為非官方文件做法，失敗時忽略）
function applyNativeCaptions() {
  if (!player || !player.unloadModule) return;
  try {
    if ($("hide-native").checked) player.unloadModule("captions");
    else player.loadModule("captions");
  } catch (_) {}
}
$("hide-native").addEventListener("change", applyNativeCaptions);

async function loadVideo(id, start = 0) {
  await apiReady;
  $("empty").hidden = true;
  $("stage").classList.remove("no-video");
  if (player) player.loadVideoById({ videoId: id, startSeconds: start });
  else
    player = new YT.Player("player", {
      videoId: id,
      playerVars: { rel: 0, cc_load_policy: 0, fs: 0, start: Math.floor(start) },
      events: {
        onReady: applyNativeCaptions,
        onStateChange: (e) => {
          // 字幕模組會在開始播放時才載入，因此每次開始播放都再套用一次
          if (e.data === YT.PlayerState.PLAYING) applyNativeCaptions();
          if (e.data === YT.PlayerState.PAUSED) saveProgress();
          if (e.data === YT.PlayerState.ENDED) saveProgress(true); // 看完了，下次從頭開始
        },
      },
    });
}

// ── 播放進度：記錄在後端（cache/<id>/progress.json），下次開啟時接著看 ──
const resumeOf = (pos, dur) => (pos < 5 || (dur && pos > dur - 10) ? 0 : pos);

function saveProgress(ended = false) {
  // 只在確實播放過（播放中／暫停）且字幕已載入時記錄，避免用 0 覆蓋掉舊進度
  if (!player || !videoId || !segs.length || !player.getPlayerState) return;
  const st = player.getPlayerState();
  if (!ended && st !== YT.PlayerState.PLAYING && st !== YT.PlayerState.PAUSED) return;
  const id = videoId, dur = player.getDuration?.() || 0;
  const pos = ended ? 0 : player.getCurrentTime();
  fetch(`/api/progress/${id}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ position: pos, duration: dur }),
    keepalive: true, // 關閉頁面時也能送出
  }).catch(() => {});
  const v = library.find((x) => x.video_id === id);
  if (v) { v.position = resumeOf(pos, dur); v.duration = dur; paintResume(v); }
}
setInterval(() => { if (player?.getPlayerState?.() === 1) saveProgress(); }, 5000);
addEventListener("pagehide", () => saveProgress());
document.addEventListener("visibilitychange", () => { if (document.hidden) saveProgress(); });

// ── 處理流程 ──
const STEP_OF = {
  queued: "subs", fetching_subtitles: "subs",
  downloading_audio: "stt", transcribing: "stt", translating: "trans",
};
const STEP_ORDER = ["subs", "stt", "trans"];

// 明顯的進度卡片：步驟、進度條、百分比；影片上也有提示（全螢幕時看得到）
function showProgress(j) {
  lastJob = j;
  const step = STEP_OF[j.stage] || "subs";
  const sttLi = document.querySelector('.steps [data-step="stt"]');
  if (step === "stt") sttLi.hidden = false; // 只有無字幕時才顯示「語音辨識」步驟
  const order = STEP_ORDER.indexOf(step);
  document.querySelectorAll(".steps li").forEach((li) => {
    const i = STEP_ORDER.indexOf(li.dataset.step);
    li.className = i < order ? "done" : i === order ? "active" : "";
  });

  const pct = Math.round((j.progress || 0) * 100);
  const determinate = (j.stage === "transcribing" || j.stage === "translating") && pct > 0;
  let label = stageLabel(j.stage);
  if (j.stage === "translating") {
    label = j.total ? t("lbl_translating_n", { done: j.done, total: j.total }) : t("lbl_translating");
  } else if (j.stage === "transcribing") label = t("lbl_transcribing");
  else if (j.stage === "downloading_audio") label = t("lbl_downloading");
  else if (j.stage === "fetching_subtitles") label = t("lbl_fetching");

  $("phint").textContent = partialShown ? t("hint_partial") : t("hint_wait");
  $("progress").hidden = false;
  $("progress").querySelector(".pbar").classList.toggle("indet", !determinate);
  $("progress").querySelector(".pbar").setAttribute("aria-valuenow", determinate ? pct : "");
  $("pfill").style.width = determinate ? `${pct}%` : "";
  $("plabel").textContent = label;
  $("ppct").textContent = determinate ? `${pct}%` : "";
  $("busy").hidden = false;
  $("busy-text").textContent = j.stage === "translating"
    ? (determinate ? t("busy_tr_pct", { pct }) : t("busy_tr")) : label;
}

function hideProgress() {
  lastJob = null;
  $("progress").hidden = true;
  $("busy").hidden = true;
  document.querySelector('.steps [data-step="stt"]').hidden = true;
}

// ── 影片標題（播放器下方）：有譯名時譯名為主、原標題為輔，與右側影片清單一致 ──
let curTitle = { title: "", trans: "" };
const libTrans = (id) => library.find((v) => v.video_id === id)?.title_trans || "";

function setTitle(title, trans) {
  curTitle = { title: title || "", trans: trans || "" };
  const el = $("vtitle");
  el.hidden = !title;
  if (!title) return;
  const both = trans && trans !== title;
  el.querySelector(".vt-main").textContent = both ? trans : title;
  const orig = el.querySelector(".vt-orig");
  orig.textContent = both ? title : "";
  orig.hidden = !both;
}

// 標題是在整支影片翻完時才翻譯的（或由舊快取背景補翻）：影片庫更新後若已有譯名，就補上
function syncTitleFromLibrary() {
  if (!videoId || !curTitle.title || curTitle.trans) return;
  const tt = libTrans(videoId);
  if (tt && tt !== curTitle.title) setTitle(curTitle.title, tt);
}

// 套用字幕資料（可能是翻譯到一半的部分字幕）
function applySubs(data) {
  setTitle(data.title, data.title_trans || libTrans(videoId));
  segs = data.segments;
  $("bar").hidden = false;
  $("transcript").hidden = false; // 預設維持收合
  $("dl-srt").hidden = $("dl-vtt").hidden = !data.complete; // 下載需等翻譯完成
  renderList();
}

// 翻譯進行中：取得「已翻好的部分」就先讓使用者用，其餘由後端背景繼續翻
async function showPartial(id, my) {
  const res = await fetch(`/api/subtitles/${id}`);
  if (!res.ok || my !== runId) return;
  const data = await res.json();
  if (my !== runId || !data.segments?.length || data.complete) return;
  partialShown = true;
  applySubs(data);
  const info = { n: data.translated, total: data.segments.length };
  setStatus(() => t("status_partial", info));
}

async function pollJob(id, my) {
  let lastDone = -1;
  for (;;) {
    if (my !== runId) return false; // 使用者已切換到別支影片
    const j = await (await fetch(`/api/jobs/${id}`)).json();
    if (j.status === "error") throw new Error(j.error);
    if (j.status === "done") { hideProgress(); return true; }
    showProgress(j);
    // 每翻完一批就更新一次可用的字幕
    if (j.stage === "translating" && j.done > 0 && j.done !== lastDone) {
      lastDone = j.done;
      await showPartial(id, my);
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

function resetView() {
  segs = []; videoId = null; current = -1; partialShown = false;
  setTitle("", "");
  $("list").innerHTML = ""; $("overlay").innerHTML = "";
  $("bar").hidden = true; $("transcript").hidden = true;
  $("transcript").open = false;
  hideProgress();
  renderLibrary();
}

async function openUrl(url) {
  saveProgress(); // 切換前先記下目前這支的進度（此時 segs／videoId 仍是舊影片）
  const my = ++runId;
  resetView();
  let resumeAt = 0;
  try {
    setStatus(() => t("status_processing"));
    const res = await fetch("/api/process", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    const info = await res.json();
    const id = info.video_id;
    resumeAt = info.position || 0;
    videoId = id;
    renderLibrary();
    loadVideo(id, resumeAt);
    loadLibrary(); // 處理中的影片會立刻出現在右側清單
    // 之前翻到一半（或正在背景翻譯）的影片：先載入已翻好的部分，馬上就能用
    if (info.status !== "done") await showPartial(id, my);
    if (!(await pollJob(id, my))) return;
    const data = await (await fetch(`/api/subtitles/${id}`)).json();
    if (my !== runId) return;
    applySubs(data);
    const total = data.segments.length;
    const ranJob = info.status !== "done"; // 這次是新跑完的：若自動檢查有修正，提示使用者
    setStatus(() => {
      const fixed = ranJob && data.review ? reviewSummary(data.review) : "";
      return t("status_done", { via: viaLabel(data.via), total }) +
        (resumeAt ? t("resume_note", { time: fmt(resumeAt) }) : "") +
        (fixed ? t("auto_checked", { summary: fixed }) : "");
    });
    loadLibrary();
  } catch (err) {
    if (my === runId) { hideProgress(); setStatus(() => serverMsg(err.message), true); }
    if (/ANTHROPIC_API_KEY/.test(err.message)) window.openSettings?.(true); // 沒有金鑰：直接請使用者輸入
  }
}

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  openUrl($("url").value);
});

// ── 影片庫（已快取的影片，含翻譯進行中／中斷的） ──
let library = [], libRetry = 0, libTimer, libKey = "";
async function loadLibrary() {
  clearTimeout(libTimer);
  try {
    library = await (await fetch("/api/library")).json();
  } catch (_) { library = []; }
  renderLibrary();
  const busy = library.some((v) => v.status === "running");
  const needTitle = library.some((v) => v.status === "done" && v.title_trans === null);
  if (busy) libTimer = setTimeout(loadLibrary, 2000); // 背景任務進行中：持續更新進度
  else if (needTitle && libRetry++ < 5) libTimer = setTimeout(loadLibrary, 4000); // 等舊快取的譯名補翻
  else if (!needTitle) libRetry = 0;
}

// ── 搜尋與標籤篩選 ──
// libQuery：搜尋文字（比對原標題、譯名、標籤）；libTags：選取中的標籤（忽略大小寫，需同時符合）
let libQuery = "", editingId = null, focusEditor = false;
const libTags = new Set();
const tagKey = (s) => s.toLowerCase();
const hasTag = (v, key) => (v.tags || []).some((x) => tagKey(x) === key);

function filteredLibrary() {
  const q = libQuery.trim().toLowerCase();
  return library.filter((v) => {
    for (const k of libTags) if (!hasTag(v, k)) return false;
    if (!q) return true;
    return [v.title, v.title_trans, ...(v.tags || [])].some((s) => (s || "").toLowerCase().includes(q));
  });
}

// 所有標籤與使用次數（同名不分大小寫，顯示第一次看到的寫法），次數多的在前
function allTags() {
  const m = new Map();
  for (const v of library) for (const tag of v.tags || []) {
    const k = tagKey(tag), cur = m.get(k);
    if (cur) cur.count++; else m.set(k, { label: tag, count: 1 });
  }
  return [...m].map(([key, o]) => ({ key, ...o }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function renderTagFilter(tags) {
  for (const k of [...libTags]) if (!tags.some((x) => x.key === k)) libTags.delete(k); // 標籤已不存在就取消選取
  const chips = tags.map((x) =>
    `<button type="button" class="tagchip${libTags.has(x.key) ? " on" : ""}" data-tag="${esc(x.key)}" aria-pressed="${libTags.has(x.key)}" title="${esc(t("tag_filter_title", { tag: x.label }))}">${esc(x.label)} <small>${x.count}</small></button>`);
  if (chips.length && (libTags.size || libQuery.trim())) {
    chips.push(`<button type="button" class="tagchip clear" data-tagclear>${esc(t("tag_clear"))}</button>`);
  }
  const html = chips.join("");
  const box = $("tag-filter");
  if (box.dataset.html !== html) { box.dataset.html = html; box.innerHTML = html; }
  $("tag-suggest").innerHTML = tags.map((x) => `<option value="${esc(x.label)}">`).join("");
}

function renderLibrary() {
  $("lib-tools").hidden = !library.length;
  if (!library.length) {
    libKey = "";
    $("tag-filter").dataset.html = ""; $("tag-filter").innerHTML = "";
    $("library").innerHTML = `<div class="lib-empty">${t("lib_empty")}</div>`;
    return;
  }
  renderTagFilter(allTags());
  const shown = filteredLibrary();
  // 只有清單結構改變時才整個重畫（避免縮圖閃爍、失去 hover／焦點）；進度只做局部更新
  const key = JSON.stringify([
    videoId, editingId, [...libTags], // 選取中的標籤也要算：卡片上標籤的「選取」樣式會跟著變
    shown.map((v) => [v.video_id, v.status, v.title, v.title_trans, v.tags]),
  ]);
  if (key !== libKey) {
    libKey = key;
    // 重畫前記下標籤輸入框的內容與焦點，避免背景進度更新時打到一半的字消失
    const ae = document.activeElement;
    const keep = ae?.classList?.contains("tag-input") ? { value: ae.value, id: ae.closest(".item")?.dataset.id } : null;
    $("library").innerHTML = shown.length
      ? libraryHtml(shown)
      : `<div class="lib-empty">${t("lib_no_match")}</div>`;
    if (editingId) {
      const inp = document.querySelector(`.item[data-id="${editingId}"] .tag-input`);
      if (inp) {
        if (keep && keep.id === editingId) inp.value = keep.value;
        if (focusEditor || keep) inp.focus();
      }
      focusEditor = false;
    }
  }
  shown.forEach((v) => { paintResume(v); paintStatus(v); });
  syncTitleFromLibrary();
}

// 標籤列：點標籤可篩選；「＋ 標籤」進入編輯。編輯中改顯示可移除的標籤與輸入框
function tagsHtml(v) {
  const tags = v.tags || [];
  if (v.video_id === editingId) {
    return `<div class="tag-editor">
      ${tags.map((x) => `<span class="tagchip mine">${esc(x)}<button type="button" data-tagdel="${esc(x)}" title="${esc(t("tag_remove", { tag: x }))}" aria-label="${esc(t("tag_remove", { tag: x }))}">×</button></span>`).join("")}
      <input class="tag-input" list="tag-suggest" maxlength="20" autocomplete="off" placeholder="${esc(t("tag_input_ph"))}" aria-label="${esc(t("tag_input_ph"))}">
      <button type="button" class="tagchip on" data-tagdone title="${esc(t("tag_done"))}" aria-label="${esc(t("tag_done"))}">✓</button>
    </div>`;
  }
  return `<div class="tags">
    ${tags.map((x) => `<button type="button" class="tagchip${libTags.has(tagKey(x)) ? " on" : ""}" data-tag="${esc(tagKey(x))}">${esc(x)}</button>`).join("")}
    <button type="button" class="tagchip add" data-tagedit="${v.video_id}" title="${esc(t("tag_add_title"))}">${esc(t("tag_add"))}</button>
  </div>`;
}

// 儲存標籤：先樂觀更新畫面，再送到後端；請求依序送出，避免快速連續操作時舊結果蓋掉新結果
let tagQueue = Promise.resolve();
function saveTags(id, tags) {
  const cur = () => library.find((x) => x.video_id === id);
  const v = cur();
  if (!v) return;
  const prev = v.tags || [];
  v.tags = tags;
  renderLibrary();
  tagQueue = tagQueue.then(async () => {
    try {
      const res = await fetch(`/api/library/${id}/tags`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      const saved = (await res.json()).tags;
      if (cur()) cur().tags = saved; // 以後端整理過的結果為準（去重、截斷）
    } catch (err) {
      if (cur()) cur().tags = prev;
      setStatus(() => serverMsg(err.message), true);
    }
    renderLibrary();
  });
}

function addTag(id, raw) {
  const v = library.find((x) => x.video_id === id);
  const tag = raw.replace(/\s+/g, " ").trim().slice(0, 20);
  if (!v || !tag) return;
  if (hasTag(v, tagKey(tag))) return;
  saveTags(id, [...(v.tags || []), tag]);
}

// 卡片的 tooltip：標題（譯名／原標題）與字幕資訊（來源、句數、日期、看到哪裡）。
// 這些資訊不佔卡片版面，滑過卡片才顯示；看到哪裡由 paintResume 隨播放更新。
function cardTip(v) {
  const names = v.title_trans && v.title_trans !== v.title ? [v.title_trans, v.title] : [v.title];
  const meta = t("meta", { via: viaLabel(v.via), count: v.count, date: new Date(v.mtime * 1000).toLocaleDateString(effLang()) });
  const seen = v.position > 0 ? t("seen", { time: fmt(v.position) }) : "";
  return [...names, meta + seen].join("\n");
}

function libraryHtml(list) {
  return list.map((v) => `
    <div class="item${v.video_id === videoId ? " active" : ""}${v.status !== "done" ? ` pending ${v.status}` : ""}" data-id="${v.video_id}" role="button" tabindex="0" title="${esc(cardTip(v))}">
      <div class="pfill"><i></i></div>
      <div class="thumb">
        <img loading="lazy" alt="" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg">
        <div class="resume" hidden><i></i></div>
        ${tagsHtml(v)}
      </div>
      <div class="info">
        ${v.title_trans && v.title_trans !== v.title
          ? `<div class="name">${esc(v.title_trans)}</div><div class="orig">${esc(v.title)}</div>`
          : `<div class="name">${esc(v.title)}</div>`}
        <div class="state" hidden></div>
      </div>
      ${v.status === "done" ? `<button class="chk" type="button" data-chk="${v.video_id}" title="${esc(t("chk"))}" aria-label="${esc(t("chk"))}">${CHECK_ICON}</button>` : ""}
      <button class="del" type="button" data-del="${v.video_id}" title="${esc(t("del"))}" aria-label="${esc(t("del"))}">✕</button>
    </div>`).join("");
}

// 單色向量圖示（currentColor）：清單加勾
const CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M4 12h6M4 17h9"/><path d="M14 15l2.6 2.6L21 12.5"/></svg>`;

// ── 字幕檢查：合併重複、修正時序（後端以本機規則處理，不呼叫 Claude） ──
function reviewSummary(r) {
  const parts = [];
  if (r.merged) parts.push(t("rv_merged", { n: r.merged }));
  if (r.retimed) parts.push(t("rv_retimed", { n: r.retimed }));
  if (r.reordered) parts.push(t("rv_reordered", { n: r.reordered }));
  if (r.dropped) parts.push(t("rv_dropped", { n: r.dropped }));
  if (r.repaired) parts.push(t("rv_repaired", { n: r.repaired }));
  return parts.join(t("rv_sep"));
}

function reviewMessage(r) {
  const summary = reviewSummary(r);
  const base = summary
    ? t("chk_done", { summary, before: r.before, after: r.after })
    : t("chk_none", { total: r.after });
  return base +
    (r.repair_error ? t("rv_repair_err", { err: r.repair_error }) : "") +
    (r.untranslated ? t("rv_untrans", { n: r.untranslated }) : "");
}

async function checkVideo(id, btn) {
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("busy");
  setStatus(() => t("chk_running"));
  try {
    const res = await fetch(`/api/library/${id}/check`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail);
    const r = await res.json();
    setStatus(() => reviewMessage(r));
    if (r.changed) {
      if (id === videoId) { // 正在播放這支：重新載入修正後的字幕
        const d = await (await fetch(`/api/subtitles/${id}`)).json();
        if (id === videoId) applySubs(d);
      }
      loadLibrary(); // 句數可能改變
    }
  } catch (err) {
    setStatus(() => serverMsg(err.message), true);
  } finally {
    btn.disabled = false;
    btn.classList.remove("busy");
  }
}

// 尚未完成的影片：半透明＋由左向右填滿的進度，讓使用者知道工作還在進行、沒有被丟棄
function paintStatus(v) {
  const el = document.querySelector(`.item[data-id="${v.video_id}"]`);
  if (!el) return;
  const pending = v.status !== "done";
  const pct = Math.round((v.progress || 0) * 100);
  const indet = v.status === "running" && (v.stage !== "translating" || pct === 0);
  el.classList.toggle("indet", indet);
  el.querySelector(".pfill i").style.width = pending && !indet ? `${pct}%` : "";
  const state = el.querySelector(".state");
  state.hidden = !pending;
  if (v.status === "running") {
    state.textContent = v.stage === "translating" && pct > 0
      ? t("lib_running_pct", { pct })
      : t("lib_stage", { stage: I18N["zh-TW"]["stage_" + v.stage] ? stageLabel(v.stage) : t("lib_processing") });
  } else if (pending) {
    state.textContent = t("lib_paused", { pct });
  }
}

// 影片庫項目上的觀看進度條（疊在縮圖上）；「看到哪裡」的文字則更新在卡片的 tooltip 裡
function paintResume(v) {
  const el = document.querySelector(`.item[data-id="${v.video_id}"]`);
  if (!el) return;
  const has = v.position > 0;
  el.title = cardTip(v);
  const bar = el.querySelector(".resume");
  bar.hidden = !(has && v.duration);
  bar.firstElementChild.style.width = `${Math.min(100, (v.position / (v.duration || 1)) * 100)}%`;
}

async function deleteVideo(id) {
  const v = library.find((x) => x.video_id === id);
  if (!confirm(t("confirm_delete", { name: v ? (v.title_trans || v.title) : id }))) return;
  const res = await fetch(`/api/library/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = (await res.json()).detail;
    setStatus(() => serverMsg(detail), true);
    return;
  }
  if (id === videoId) {
    ++runId;
    try { player?.stopVideo(); } catch (_) {}
    resetView();
    $("empty").hidden = false;
    $("stage").classList.add("no-video"); // 播放器會停在剛才的縮圖，要藏起來才看得到提示
    setStatus(() => t("status_deleted"));
  }
  loadLibrary();
}

// 篩選列：點標籤切換（可複選）、清除篩選、搜尋
$("tag-filter").addEventListener("click", (e) => {
  if (e.target.closest("[data-tagclear]")) { libTags.clear(); libQuery = ""; $("lib-search").value = ""; renderLibrary(); return; }
  const chip = e.target.closest("[data-tag]");
  if (!chip) return;
  const k = chip.dataset.tag;
  libTags.has(k) ? libTags.delete(k) : libTags.add(k);
  renderLibrary();
});
$("lib-search").addEventListener("input", (e) => { libQuery = e.target.value; renderLibrary(); });

$("library").addEventListener("click", (e) => {
  // 標籤相關的點擊都不應該開啟影片
  const tag = e.target.closest("[data-tag]");
  if (tag) { e.stopPropagation(); const k = tag.dataset.tag; libTags.has(k) ? libTags.delete(k) : libTags.add(k); renderLibrary(); return; }
  const edit = e.target.closest("[data-tagedit]");
  if (edit) { e.stopPropagation(); editingId = edit.dataset.tagedit; focusEditor = true; renderLibrary(); return; }
  const tdel = e.target.closest("[data-tagdel]");
  if (tdel) {
    e.stopPropagation();
    const id = tdel.closest(".item").dataset.id, v = library.find((x) => x.video_id === id);
    if (v) { focusEditor = true; saveTags(id, (v.tags || []).filter((x) => x !== tdel.dataset.tagdel)); }
    return;
  }
  if (e.target.closest("[data-tagdone]")) { e.stopPropagation(); editingId = null; renderLibrary(); return; }
  if (e.target.closest(".tag-editor")) return;
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); deleteVideo(del.dataset.del); return; }
  const chk = e.target.closest("[data-chk]");
  if (chk) { e.stopPropagation(); checkVideo(chk.dataset.chk, chk); return; }
  const item = e.target.closest(".item");
  if (item && item.dataset.id !== videoId) openUrl(item.dataset.id);
});
$("library").addEventListener("keydown", (e) => {
  if (e.target.classList.contains("tag-input")) {
    if (e.isComposing || e.keyCode === 229) return; // 輸入法選字中（例如注音按 Enter 確認），不要當成新增
    const id = e.target.closest(".item").dataset.id, v = library.find((x) => x.video_id === id);
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const val = e.target.value;
      e.target.value = ""; // 先清空：addTag 會同步重畫，重畫時會保留輸入框目前的內容
      focusEditor = true;
      addTag(id, val);
    } else if (e.key === "Backspace" && !e.target.value && v?.tags?.length) {
      focusEditor = true;
      saveTags(id, v.tags.slice(0, -1)); // 輸入框是空的時按 Backspace：移除最後一個標籤
    } else if (e.key === "Escape") {
      editingId = null; renderLibrary();
    }
    return;
  }
  if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("item")) {
    e.preventDefault();
    if (e.target.dataset.id !== videoId) openUrl(e.target.dataset.id);
  }
});

applyStaticI18n();
paintCtrls();
loadLibrary();
