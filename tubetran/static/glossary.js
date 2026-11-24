// ── 術語表編輯：播放器下方工具列的字典圖示 ──
// 檢視、修改、新增、刪除這支影片的術語（{原文: 譯法}），可只儲存，或儲存後用它重新翻譯整支影片。
// 依賴 app.js 的全域：videoId、library、$、esc、t、serverMsg、setStatus、openUrl。
// app.js 在套用字幕時呼叫 glossarySync(data)，換影片／重設畫面時呼叫 glossaryReset()。
(() => {
  const SKIP_LANGS = ["zh-TW", "zh-Hant", "zh-Hant-TW"]; // 原文已是繁體中文：不翻譯，也就沒有術語表
  const MAX_TERMS = 40; // 和後端的 GLOSSARY_MAX 一致；後端會再整理一次，以它為準
  const btn = $("gl-toggle"), panel = $("gl-panel"), rows = $("gl-rows");
  let draft = [];      // [{ term, trans }]：畫面上正在編輯的內容
  let edited = false;  // 後端回報：這份術語表是否被手動編輯過
  let loadedFor = null, busy = false, msgKey = null, seq = 0;

  const isOpen = () => !panel.hidden;

  function setMsg(text, err = false) {
    $("gl-msg").textContent = text || "";
    $("gl-msg").className = err ? "err" : "";
  }

  function setBusy(b) {
    busy = b;
    for (const id of ["gl-add", "gl-reset", "gl-save", "gl-retrans"]) $(id).disabled = b;
  }

  function dupKeys() {
    const seen = new Set(), dup = new Set();
    for (const r of draft) {
      const k = r.term.trim().replace(/\s+/g, " ").toLowerCase();
      if (!k) continue;
      (seen.has(k) ? dup : seen).add(k);
    }
    return dup;
  }

  function markDups() {
    const dup = dupKeys();
    rows.querySelectorAll(".gl-row").forEach((row, i) => {
      const k = draft[i].term.trim().replace(/\s+/g, " ").toLowerCase();
      row.querySelector(".gl-term").classList.toggle("dup", dup.has(k));
    });
    if (!busy && !msgKey) setMsg(dup.size ? t("gl_dup") : "");
  }

  function renderState() {
    $("gl-state").textContent = loadedFor ? t(edited ? "gl_edited" : "gl_auto") : "";
    $("gl-add").disabled = busy || draft.length >= MAX_TERMS;
    $("gl-add").title = draft.length >= MAX_TERMS ? t("gl_max", { n: MAX_TERMS }) : "";
  }

  function render() {
    rows.innerHTML = draft.length
      ? draft.map((r, i) => `<div class="gl-row" data-i="${i}">
          <input class="gl-term" value="${esc(r.term)}" maxlength="60" spellcheck="false" autocomplete="off"
                 placeholder="${esc(t("gl_term"))}" aria-label="${esc(t("gl_term"))}">
          <span class="gl-arrow" aria-hidden="true">→</span>
          <input class="gl-trans" value="${esc(r.trans)}" maxlength="60" spellcheck="false" autocomplete="off"
                 placeholder="${esc(t("gl_trans"))}" aria-label="${esc(t("gl_trans"))}">
          <button class="gl-del" type="button" title="${esc(t("gl_del"))}" aria-label="${esc(t("gl_del"))}">✕</button>
        </div>`).join("")
      : `<p class="gl-empty">${esc(t("gl_empty"))}</p>`;
    renderState();
    markDups();
    applyFilter();
  }

  // 搜尋：原文或譯法含有關鍵字（不分大小寫）的列才顯示；其他列只是隱藏，draft 與儲存的內容不變
  const query = () => $("gl-q").value.trim().toLowerCase();
  const visibleRows = () => [...rows.querySelectorAll(".gl-row:not([hidden])")];

  function applyFilter() {
    const q = query();
    let shown = 0;
    rows.querySelectorAll(".gl-row").forEach((row, i) => {
      const r = draft[i];
      const hit = !q || r.term.toLowerCase().includes(q) || r.trans.toLowerCase().includes(q);
      row.hidden = !hit;
      if (hit) shown++;
    });
    rows.querySelector(".gl-none")?.remove();
    if (q && draft.length && !shown) rows.insertAdjacentHTML("beforeend", `<p class="gl-empty gl-none">${esc(t("gl_none"))}</p>`);
    $("gl-count").textContent = q && draft.length ? t("gl_count", { n: shown, total: draft.length }) : "";
  }

  async function load() {
    const id = videoId, my = ++seq;
    setMsg(t("gl_loading")); msgKey = "gl_loading";
    try {
      const res = await fetch(`/api/library/${id}/glossary`);
      if (!res.ok) throw new Error((await res.json()).detail);
      const data = await res.json();
      if (my !== seq || id !== videoId) return;
      draft = data.glossary.map((g) => ({ term: g.term, trans: g.trans }));
      edited = data.edited; loadedFor = id;
      msgKey = null; setMsg("");
      render();
    } catch (err) {
      if (my !== seq) return;
      msgKey = null; setMsg(serverMsg(err.message), true);
    }
  }

  function setOpen(open, focus = false) {
    panel.hidden = !open;
    btn.setAttribute("aria-pressed", String(open));
    btn.setAttribute("aria-expanded", String(open));
    if (!open) { if (focus) btn.focus(); return; }
    if (loadedFor !== videoId) { draft = []; loadedFor = null; render(); load(); } // 每支影片第一次展開時才載入
    else render();
  }

  // 後端整理後的結果為準（去重、截斷）
  const body = () => draft.map((r) => ({ term: r.term, trans: r.trans }));

  async function save() {
    const id = videoId;
    const res = await fetch(`/api/library/${id}/glossary`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ glossary: body() }),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    const data = await res.json();
    if (id === videoId) {
      draft = data.glossary.map((g) => ({ term: g.term, trans: g.trans }));
      edited = data.edited; render();
    }
    return data;
  }

  async function run(job) {
    if (busy || !videoId) return;
    setBusy(true); msgKey = null; setMsg("");
    try { await job(); }
    catch (err) {
      setMsg(serverMsg(err.message), true);
      if (/ANTHROPIC_API_KEY/.test(err.message)) window.openSettings?.(true);
    } finally { setBusy(false); renderState(); }
  }

  const videoName = () => {
    const v = library.find((x) => x.video_id === videoId);
    return v ? (v.title_trans || v.title) : videoId;
  };

  // 重新翻譯：後端把目前的翻譯結果丟掉、開一個新任務；和 ↻ 一樣用 openUrl 切回這支影片顯示進度
  async function retranslate(resetGlossary) {
    const id = videoId;
    const res = await fetch(`/api/library/${id}/retranslate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reset_glossary: resetGlossary }),
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    openUrl(id); // resetView 會呼叫 glossaryReset() 收起面板
  }

  btn.addEventListener("click", () => setOpen(!isOpen()));

  $("gl-add").addEventListener("click", () => {
    if (busy || draft.length >= MAX_TERMS) return;
    $("gl-q").value = ""; // 新的一列是空的，會被搜尋濾掉：先清掉搜尋
    draft.push({ term: "", trans: "" });
    render();
    rows.lastElementChild?.querySelector(".gl-term")?.focus();
    rows.scrollTop = rows.scrollHeight;
  });

  rows.addEventListener("input", (e) => {
    const row = e.target.closest(".gl-row");
    if (!row) return;
    const r = draft[+row.dataset.i];
    if (e.target.classList.contains("gl-term")) r.term = e.target.value;
    else r.trans = e.target.value;
    markDups();
    applyFilter(); // 改到的字可能讓這一列不再符合搜尋，但不要在打字時就把它藏起來：只更新計數
    row.hidden = false;
  });

  $("gl-q").addEventListener("input", applyFilter);
  $("gl-q").addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.isComposing || e.keyCode === 229 || !$("gl-q").value) return;
    e.preventDefault(); e.stopPropagation(); // 有搜尋字時，Esc 先清掉搜尋；再按一次才收起面板
    $("gl-q").value = ""; applyFilter();
  });

  rows.addEventListener("click", (e) => {
    const del = e.target.closest(".gl-del");
    if (!del || busy) return;
    const i = +del.closest(".gl-row").dataset.i;
    draft.splice(i, 1);
    render();
    const vis = visibleRows();
    (vis[Math.min(i, vis.length - 1)]?.querySelector(".gl-del") || $("gl-add")).focus();
  });

  // 在「原文」欄按 Enter：跳到同一列的「譯法」；在「譯法」欄按 Enter：跳到下一列的「原文」（最後一列就新增一列）
  rows.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
    const row = e.target.closest(".gl-row");
    if (!row || !e.target.matches("input")) return;
    e.preventDefault();
    if (e.target.classList.contains("gl-term")) { row.querySelector(".gl-trans").focus(); return; }
    const next = row.nextElementSibling;
    if (next) next.querySelector(".gl-term").focus(); else $("gl-add").click();
  });

  $("gl-save").addEventListener("click", () => run(async () => {
    const data = await save();
    setMsg(t("gl_saved", { n: data.glossary.length }));
  }));

  $("gl-retrans").addEventListener("click", () => {
    if (busy || !confirm(t("confirm_gl_retrans", { name: videoName() }))) return;
    run(async () => { await save(); await retranslate(false); });
  });

  $("gl-reset").addEventListener("click", () => {
    if (busy || !confirm(t("confirm_gl_reset", { name: videoName() }))) return;
    run(() => retranslate(true));
  });

  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); setOpen(false, true); }
  });

  // ── app.js 的掛鉤 ──
  window.glossarySync = (data) => {
    const show = !!data.complete && !SKIP_LANGS.includes(data.lang);
    btn.hidden = !show;
    if (!show && isOpen()) setOpen(false);
  };
  window.glossaryReset = () => {
    seq++; loadedFor = null; draft = []; msgKey = null; setMsg(""); $("gl-q").value = "";
    btn.hidden = true;
    setOpen(false);
  };
  window.glossaryLang = () => { if (isOpen()) render(); }; // 切換介面語言：列的提示文字重畫
})();
