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
  // 有沒有未儲存的修改：和「後端目前的內容」（載入或儲存完的樣子）比較。空白列（新增了還沒填）不算修改；前後空白與連續空白也不算。
  let baseline = "[]";
  const sig = () => JSON.stringify(draft
    .map((r) => [r.term.trim().replace(/\s+/g, " "), r.trans.trim()])
    .filter(([a, b]) => a || b));
  const isDirty = () => !!loadedFor && sig() !== baseline;
  // 桌面版：有沒有未儲存的修改要先告訴 Python（Alt+F4、工作列關閉視窗不經過網頁，網頁收不到通知，只能由 Python 在關閉事件裡問）。
  // 只在狀態或提示文字（介面語言）改變時才通知
  let notified = "";
  function notifyUnsaved(dirty) {
    const msg = dirty ? t("confirm_gl_discard") : "";
    if (msg === notified) return;
    notified = msg;
    try { window.pywebview?.api?.set_unsaved?.(msg)?.catch?.(() => {}); } catch (_) {}
  }

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
    const dirty = isDirty();
    $("gl-state").textContent = loadedFor ? t(edited ? "gl_edited" : "gl_auto") + (dirty ? " · " + t("gl_dirty") : "") : "";
    $("gl-state").classList.toggle("dirty", dirty);
    btn.dataset.dirty = dirty ? "1" : "0"; // 鈕上的小圓點：收合了也看得出有未儲存的修改
    notifyUnsaved(dirty);
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
      baseline = sig();
      msgKey = null; setMsg("");
      render();
    } catch (err) {
      if (my !== seq) return;
      msgKey = null; setMsg(serverMsg(err.message), true);
    }
  }

  function setOpen(open, focus = false) {
    panel.hidden = !open;
    if (open) $("transcript").open = false; // 面板在字幕清單的下面：展開術語表時收起字幕清單（反過來也一樣，見下面的 toggle 監聽）
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
      edited = data.edited; baseline = sig(); render();
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
    baseline = sig(); // 這些修改已經由使用者明確處理（儲存，或按「重設」捨棄），切換時不要再問一次
    openUrl(id); // resetView 會呼叫 glossaryReset() 收起面板
  }

  btn.addEventListener("click", () => setOpen(!isOpen()));
  // 面板在字幕清單卡片的下面：兩者互斥，展開字幕清單時術語表自動收合（展開術語表時收起字幕清單在 setOpen 裡）
  $("transcript").addEventListener("toggle", () => { if ($("transcript").open && isOpen()) setOpen(false); });

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
    renderState(); // 未儲存的標記跟著打字更新
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

  $("gl-retrans").addEventListener("click", async () => {
    if (busy || !(await appConfirm(t("confirm_gl_retrans", { name: videoName() }), { ok: t("modal_retrans") })) || busy) return;
    run(async () => { await save(); await retranslate(false); });
  });

  $("gl-reset").addEventListener("click", async () => {
    if (busy || !(await appConfirm(t("confirm_gl_reset", { name: videoName() }), { ok: t("modal_reset") })) || busy) return;
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
    seq++; loadedFor = null; draft = []; baseline = "[]"; msgKey = null; setMsg(""); $("gl-q").value = "";
    btn.hidden = true; btn.dataset.dirty = "0"; notifyUnsaved(false);
    setOpen(false);
  };
  window.glossaryLang = () => { if (isOpen()) render(); notifyUnsaved(isDirty()); }; // 切換介面語言：列的提示文字重畫，通知 Python 的提示文字也換
  // 離開前的確認：切換影片（app.js 的 openUrl）、桌面版自製的關閉鈕（desktop.js）會先問；沒有未儲存的修改就直接過
  // 離開前的確認，用自製對話框（appConfirm，見 app.js）。沒有未儲存的修改就直接過
  window.glossaryConfirmLeave = () => (isDirty()
    ? appConfirm(t("confirm_gl_discard"), { ok: t("modal_discard"), cancel: t("modal_keep") })
    : Promise.resolve(true));
  // Alt+F4、工作列關閉視窗：Python 的關閉事件先取消這次關閉，再呼叫這裡；使用者確定放棄才真的關（window_close）
  window.askLeaveThenClose = async () => {
    if (!(await window.glossaryConfirmLeave())) return;
    try { saveProgress(); } catch (_) {}
    setTimeout(() => window.pywebview?.api?.window_close?.(), 120); // 讓進度的請求有時間送出
  };  // 關閉分頁、重新整理、瀏覽器模式關視窗：交給瀏覽器的離開確認（文字由瀏覽器決定）
  addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
})();
