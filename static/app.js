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

// ── 主題 ──
// 三種模式：auto（預設，跟隨系統）／light／dark。auto 時不設定 data-theme，交給 CSS 的 prefers-color-scheme
const root = document.documentElement;
const darkMQ = matchMedia("(prefers-color-scheme: dark)");
function getTheme() {
  try { const v = localStorage.getItem("theme"); return v === "light" || v === "dark" ? v : "auto"; }
  catch (_) { return "auto"; }
}
// 分頁圖示（icon）依「實際生效的主題」切換：淺色＝RX-78-2、深色＝EVA 初號機
function updateFavicon() {
  const th = getTheme(), dark = th === "dark" || (th === "auto" && darkMQ.matches);
  $("favicon").href = `/static/logo/${dark ? "tubetran-eva-dark-icon.svg" : "tubetran-rx78-light-icon.svg"}`;
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
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("stage").requestFullscreen?.();
}
$("fs").addEventListener("click", toggleFullscreen);
document.addEventListener("keydown", (e) => {
  if ((e.key === "f" || e.key === "F") && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {
    toggleFullscreen();
  }
});
let idleTimer;
$("stage").addEventListener("mousemove", () => {
  $("stage").classList.add("active");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => $("stage").classList.remove("active"), 2500);
});

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

function renderLibrary() {
  $("lib-count").textContent = library.length ? String(library.length) : "";
  if (!library.length) {
    libKey = "";
    $("library").innerHTML = `<div class="lib-empty">${t("lib_empty")}</div>`;
    return;
  }
  // 只有清單結構改變時才整個重畫（避免縮圖閃爍、失去 hover／焦點）；進度只做局部更新
  const key = JSON.stringify([videoId, library.map((v) => [v.video_id, v.status, v.title, v.title_trans])]);
  if (key !== libKey) {
    libKey = key;
    $("library").innerHTML = libraryHtml();
  }
  library.forEach((v) => { paintResume(v); paintStatus(v); });
  syncTitleFromLibrary();
}

function libraryHtml() {
  return library.map((v) => `
    <div class="item${v.video_id === videoId ? " active" : ""}${v.status !== "done" ? ` pending ${v.status}` : ""}" data-id="${v.video_id}" role="button" tabindex="0">
      <div class="pfill"><i></i></div>
      <img loading="lazy" alt="" src="https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg">
      <div class="info">
        ${v.title_trans && v.title_trans !== v.title
          ? `<div class="name" title="${esc(v.title_trans)}">${esc(v.title_trans)}</div><div class="orig" title="${esc(v.title)}">${esc(v.title)}</div>`
          : `<div class="name" title="${esc(v.title)}">${esc(v.title)}</div>`}
        <div class="meta">${esc(t("meta", { via: viaLabel(v.via), count: v.count, date: new Date(v.mtime * 1000).toLocaleDateString(effLang()) }))}<span class="seen"></span></div>
        <div class="state" hidden></div>
        <div class="resume" hidden><i></i></div>
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

// 影片庫項目上的「上次看到」文字與細進度條
function paintResume(v) {
  const el = document.querySelector(`.item[data-id="${v.video_id}"]`);
  if (!el) return;
  const has = v.position > 0;
  el.querySelector(".seen").textContent = has ? t("seen", { time: fmt(v.position) }) : "";
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
    setStatus(() => t("status_deleted"));
  }
  loadLibrary();
}

$("library").addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); deleteVideo(del.dataset.del); return; }
  const chk = e.target.closest("[data-chk]");
  if (chk) { e.stopPropagation(); checkVideo(chk.dataset.chk, chk); return; }
  const item = e.target.closest(".item");
  if (item && item.dataset.id !== videoId) openUrl(item.dataset.id);
});
$("library").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("item")) {
    e.preventDefault();
    if (e.target.dataset.id !== videoId) openUrl(e.target.dataset.id);
  }
});

applyStaticI18n();
paintCtrls();
loadLibrary();
