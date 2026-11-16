// 設定面板：API 金鑰（只顯示遮罩後的內容）、翻譯模型、STT 模型。
// 依賴 app.js 的 $、setStatus 與 i18n.js 的 t()、serverMsg()。
(function () {
  const btn = $("settings-btn"), panel = $("settings-panel");
  const keyIn = $("set-key"), tSel = $("set-tmodel"), wSel = $("set-wmodel");
  let masked = "";           // 後端回傳的遮罩字串；輸入框內容沒變就代表「不更換金鑰」
  let state = null;          // 最近一次的 /api/settings
  let models = null;         // 最近一次的 /api/models
  let msg = { key: "", err: false }; // 底部訊息（語系切換時要能重新翻譯）

  const isOpen = () => !panel.hidden;

  function setMsg(key, err = false, params) {
    msg = { key, err, params };
    paintMsg();
  }
  function paintMsg() {
    const el = $("set-msg");
    el.textContent = msg.key ? t(msg.key, msg.params) : "";
    el.className = msg.err ? "err" : "";
  }

  function fillSelect(sel, ids, labels, current) {
    sel.replaceChildren();
    const list = ids.includes(current) || !current ? ids : [current, ...ids];
    for (const id of list) {
      const o = document.createElement("option");
      o.value = id;
      o.textContent = !ids.includes(id) ? t("set_current", { id }) : (labels[id] || id);
      sel.appendChild(o);
    }
    sel.value = current;
  }

  function paint() {
    if (!state) return;
    if (state.version) $("set-ver").textContent = `TubeTran ${/^\d/.test(state.version) ? "v" : ""}${state.version}`;
    const lk = state.locked || {};
    const lockMsg = (name) => t("set_locked", { name });
    keyIn.disabled = !!lk.api_key;
    tSel.disabled = !!lk.translate_model;
    wSel.disabled = !!lk.whisper_model;
    $("set-save").disabled = !!(lk.api_key && lk.translate_model && lk.whisper_model);

    const key = $("set-key-hint");
    key.textContent = lk.api_key ? lockMsg("ANTHROPIC_API_KEY") : (state.has_key ? t("set_key_ok") : t("set_key_missing"));
    key.className = !lk.api_key && !state.has_key ? "warn" : "";
    $("set-wmodel-hint").textContent = lk.whisper_model ? lockMsg("WHISPER_MODEL") : t("set_wmodel_hint");

    // 翻譯模型
    const cur = tSel.value && models ? tSel.value : state.translate_model;
    const tm = models && models.translate;
    const ids = tm ? tm.models.map((m) => m.id) : [];
    const labels = Object.fromEntries((tm ? tm.models : []).map((m) => [m.id, `${m.name}（${m.id}）`]));
    fillSelect(tSel, ids, labels, cur);
    const hint = $("set-tmodel-hint");
    if (lk.translate_model) hint.textContent = lockMsg("TRANSLATE_MODEL");
    else if (!models) hint.textContent = t("set_tmodel_loading");
    else if (tm.error) hint.textContent = t("set_tmodel_" + tm.error);
    else hint.textContent = t("set_tmodel_ok");
    hint.className = !lk.translate_model && models && tm.error ? "warn" : "";

    // STT 模型
    const wcur = wSel.value && models ? wSel.value : state.whisper_model;
    const wids = models ? models.whisper : [];
    fillSelect(wSel, wids, {}, wcur);
    paintMsg();
  }

  async function loadState() {
    state = await (await fetch("/api/settings")).json();
    masked = state.api_key;
    keyIn.value = masked;
    return state;
  }
  async function loadModels() {
    models = null;
    paint();
    try { models = await (await fetch("/api/models")).json(); }
    catch (_) { models = { translate: { models: [], error: "failed" }, whisper: [] }; }
    paint();
  }

  async function open(needKey = false) {
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    setMsg(needKey ? "set_need_key" : "", needKey);
    await loadState();
    paint();
    keyIn.focus();
    keyIn.select();
    await loadModels();
  }
  function close(returnFocus = false) {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (returnFocus) btn.focus();
  }
  window.openSettings = open; // app.js：處理影片時發現沒有金鑰，就請使用者輸入

  btn.addEventListener("click", () => (isOpen() ? close() : open()));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen()) close(true); });
  document.addEventListener("pointerdown", (e) => {
    if (isOpen() && !panel.contains(e.target) && !btn.contains(e.target)) close();
  });
  // 選單點開時，焦點與點擊都還在面板內，不需特別處理；靠鍵盤離開面板（Tab 出去）也收起
  panel.addEventListener("focusout", (e) => {
    if (isOpen() && e.relatedTarget && !panel.contains(e.relatedTarget) && !btn.contains(e.relatedTarget)) close();
  });

  keyIn.addEventListener("focus", () => keyIn.select()); // 點進去整段選取：直接貼上就會取代

  $("set-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { translate_model: tSel.value, whisper_model: wSel.value };
    const typed = keyIn.value.trim();
    const keyChanged = typed !== "" && typed !== masked;
    if (keyChanged) body.api_key = typed;
    setMsg("set_saving");
    try {
      const res = await fetch("/api/settings", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || res.statusText);
      state = data;
      masked = data.api_key;
      keyIn.value = masked; // 立刻換回遮罩，畫面上不留下完整金鑰
      setMsg("set_saved");
      paint();
      if (keyChanged) await loadModels(); // 換了金鑰：用新金鑰重新取得可用的模型清單
    } catch (err) {
      setMsg("set_failed", true, { err: serverMsg(err.message) });
    }
  });

  window.repaintSettings = paint; // 切換介面語言時重畫動態文字

  // 啟動時檢查：沒有金鑰就直接打開面板
  fetch("/api/settings").then((r) => r.json()).then((s) => { if (!s.has_key) open(true); }).catch(() => {});
})();
