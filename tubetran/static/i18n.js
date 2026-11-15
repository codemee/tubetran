// 介面語系：auto（預設，跟隨系統／瀏覽器語言）、zh-TW、en
const I18N = {
  "zh-TW": {
    title: "水管譯工",
    url_ph: "貼上 YouTube 網址，按 Enter 載入",
    load: "載入",
    ctrl_title: "{label}：{state}（點擊切換）",
    theme_label: "主題", theme_auto_t: "跟隨系統（預設）",
    theme_light_t: "淺色", theme_dark_t: "深色",
    lang_label: "語言", lang_auto_t: "跟隨系統（預設）", lang_zh_t: "繁體中文", lang_en_t: "English",
    set_btn: "設定", set_title: "設定",
    set_key: "Claude API 金鑰", set_key_ph: "貼上 API 金鑰（sk-ant-…）",
    set_key_ok: "已設定；要更換請直接貼上新的金鑰。",
    set_key_missing: "尚未設定金鑰：沒有它就無法翻譯。請貼上你的 Claude API 金鑰後按「儲存」。",
    set_tmodel: "翻譯模型", set_tmodel_ok: "清單來自 Anthropic，是這把金鑰實際可用的模型。",
    set_tmodel_loading: "正在取得模型清單…",
    set_tmodel_no_key: "儲存有效的金鑰後，才能取得模型清單。",
    set_tmodel_auth: "金鑰無效或沒有權限，無法取得模型清單。",
    set_tmodel_failed: "暫時無法取得模型清單（網路或服務問題）；目前仍可使用已設定的模型。",
    set_wmodel: "語音辨識（STT）模型", set_wmodel_hint: "只在影片沒有字幕時使用；模型越大越準，也越慢、下載越大。",
    set_current: "{id}（目前設定）",
    set_locked: "由環境變數 {name} 指定，優先於 .env，無法在此修改；要改請調整該環境變數。",
    set_save: "儲存", set_saving: "儲存中…", set_saved: "已儲存，之後開始的任務會使用新設定。",
    set_failed: "儲存失敗：{err}", set_need_key: "請先輸入 Claude API 金鑰，才能翻譯影片。",
    empty: "貼上 YouTube 網址，或從右側選一支已翻譯的影片",
    fs: "全螢幕 (F)",
    step_subs: "取得字幕", step_stt: "語音辨識", step_trans: "翻譯",
    mode_label: "字幕顯示模式", mode_both: "雙語", mode_orig: "原文", mode_trans: "譯文",
    hide_native: "隱藏 YouTube 原字幕",
    dl_srt: "下載 SRT", dl_vtt: "下載 VTT",
    side_title: "已翻譯的影片",
    lib_empty: "還沒有已翻譯的影片。<br>翻譯完成後會出現在這裡，之後可以快速重看。",
    lib_search_ph: "搜尋標題或標籤",
    lib_no_match: "沒有符合的影片。<br>試試別的關鍵字，或清除篩選條件。",
    tag_filter_label: "依標籤篩選",
    tag_clear: "清除篩選",
    tag_add: "＋ 標籤", tag_add_title: "新增或編輯標籤",
    tag_input_ph: "輸入標籤，按 Enter 新增", tag_done: "完成編輯", tag_remove: "移除標籤「{tag}」",
    tag_filter_title: "篩選：{tag}",
    del: "刪除快取",
    chk: "檢查字幕（合併重複、修正時間、補翻空白譯文）",
    chk_running: "檢查字幕中…",
    chk_none: "檢查完成：沒有發現問題（共 {total} 句）",
    chk_done: "檢查完成：{summary}（{before} → {after} 句）",
    rv_merged: "合併重複 {n} 句", rv_retimed: "修正時間 {n} 處",
    rv_reordered: "調整順序 {n} 處", rv_dropped: "移除空白 {n} 句",
    rv_repaired: "補翻空白譯文 {n} 句", rv_repair_err: "；補翻失敗：{err}",
    rv_sep: "、", rv_untrans: "；另有 {n} 句尚無譯文",
    auto_checked: "　·　已自動檢查並修正：{summary}",
    pending_tr: "翻譯中…",
    stage_queued: "排隊中", stage_fetching_subtitles: "取得字幕中",
    stage_downloading_audio: "無字幕，下載音檔中", stage_transcribing: "語音辨識中",
    stage_translating: "翻譯中", stage_done: "完成", stage_cached: "已有快取",
    via_manual: "人工字幕", via_auto: "自動字幕", via_whisper: "Whisper",
    lbl_translating_n: "正在翻譯字幕…已翻譯 {done} / {total} 句",
    lbl_translating: "正在翻譯字幕…",
    lbl_transcribing: "正在辨識語音…",
    lbl_downloading: "沒有字幕，正在下載音檔…",
    lbl_fetching: "正在取得字幕…",
    busy_tr_pct: "字幕翻譯中 {pct}%", busy_tr: "字幕翻譯中…",
    hint_partial: "已翻譯的部分可以先使用，其餘會在背景繼續翻譯，完成後自動更新。",
    hint_wait: "完成前字幕還不能使用，影片可以先播放。",
    tx_title: "字幕清單（{total} 句）",
    tx_title_partial: "字幕清單（已翻譯 {n} / {total} 句）",
    status_processing: "處理中…",
    status_partial: "部分字幕可用（已翻譯 {n} / {total} 句），其餘在背景翻譯中",
    status_done: "{via}　·　共 {total} 句",
    resume_note: "　·　已從 {time} 接著播放",
    status_deleted: "已刪除快取",
    lib_running_pct: "翻譯中 {pct}%，完成後可直接播放",
    lib_stage: "{stage}…",
    lib_processing: "處理中",
    lib_paused: "已中斷於 {pct}%，點擊繼續翻譯",
    seen: " · 看到 {time}",
    meta: "{via} · {count} 句 · {date}",
    confirm_delete: "刪除「{name}」的快取？\n字幕、翻譯與已下載的音檔都會被清除，再次觀看需要重新處理（並重新呼叫 Claude）。",
  },
  en: {
    title: "TubeTran",
    url_ph: "Paste a YouTube URL and press Enter",
    load: "Load",
    ctrl_title: "{label}: {state} (click to switch)",
    theme_label: "Theme", theme_auto_t: "Follow system (default)",
    theme_light_t: "Light", theme_dark_t: "Dark",
    lang_label: "Language", lang_auto_t: "Follow system (default)", lang_zh_t: "繁體中文", lang_en_t: "English",
    set_btn: "Settings", set_title: "Settings",
    set_key: "Claude API key", set_key_ph: "Paste your API key (sk-ant-…)",
    set_key_ok: "A key is set. To replace it, just paste a new one.",
    set_key_missing: "No key yet — translation can't run without one. Paste your Claude API key and press Save.",
    set_tmodel: "Translation model", set_tmodel_ok: "Listed by Anthropic: the models this key can actually use.",
    set_tmodel_loading: "Loading the model list…",
    set_tmodel_no_key: "Save a valid key to load the model list.",
    set_tmodel_auth: "The key is invalid or lacks permission, so the model list can't be loaded.",
    set_tmodel_failed: "Couldn't load the model list right now (network or service issue); the configured model still works.",
    set_wmodel: "Speech-to-text (STT) model", set_wmodel_hint: "Only used when a video has no captions. Bigger models are more accurate, but slower and a larger download.",
    set_current: "{id} (current)",
    set_locked: "Set by the {name} environment variable, which takes priority over .env, so it can't be changed here. Change that variable instead.",
    set_save: "Save", set_saving: "Saving…", set_saved: "Saved. Jobs started from now on use the new settings.",
    set_failed: "Couldn't save: {err}", set_need_key: "Enter your Claude API key first so videos can be translated.",
    empty: "Paste a YouTube URL, or pick a translated video from the list on the right",
    fs: "Fullscreen (F)",
    step_subs: "Captions", step_stt: "Speech-to-text", step_trans: "Translate",
    mode_label: "Subtitle display mode", mode_both: "Bilingual", mode_orig: "Original", mode_trans: "Translation",
    hide_native: "Hide YouTube's captions",
    dl_srt: "Download SRT", dl_vtt: "Download VTT",
    side_title: "Translated videos",
    lib_empty: "No translated videos yet.<br>They will show up here once translated, so you can quickly watch them again.",
    lib_search_ph: "Search titles or tags",
    lib_no_match: "No matching videos.<br>Try another keyword, or clear the filters.",
    tag_filter_label: "Filter by tag",
    tag_clear: "Clear filters",
    tag_add: "+ Tag", tag_add_title: "Add or edit tags",
    tag_input_ph: "Type a tag and press Enter", tag_done: "Done editing", tag_remove: "Remove tag \"{tag}\"",
    tag_filter_title: "Filter: {tag}",
    del: "Delete cache",
    chk: "Check subtitles (merge duplicates, fix timing, fill blank translations)",
    chk_running: "Checking subtitles…",
    chk_none: "Check complete: no problems found ({total} lines)",
    chk_done: "Check complete: {summary} ({before} → {after} lines)",
    rv_merged: "merged {n} duplicate lines", rv_retimed: "fixed {n} timing issues",
    rv_reordered: "reordered {n} out-of-order lines", rv_dropped: "removed {n} empty lines",
    rv_repaired: "filled in {n} blank translations", rv_repair_err: "; filling in blank translations failed: {err}",
    rv_sep: ", ", rv_untrans: "; {n} lines still have no translation",
    auto_checked: "  ·  Auto-checked and fixed: {summary}",
    pending_tr: "Translating…",
    stage_queued: "Queued", stage_fetching_subtitles: "Fetching captions",
    stage_downloading_audio: "No captions, downloading audio", stage_transcribing: "Transcribing speech",
    stage_translating: "Translating", stage_done: "Done", stage_cached: "Cached",
    via_manual: "Manual captions", via_auto: "Auto captions", via_whisper: "Whisper",
    lbl_translating_n: "Translating subtitles… {done} / {total} lines done",
    lbl_translating: "Translating subtitles…",
    lbl_transcribing: "Transcribing speech…",
    lbl_downloading: "No captions — downloading audio…",
    lbl_fetching: "Fetching captions…",
    busy_tr_pct: "Translating subtitles {pct}%", busy_tr: "Translating subtitles…",
    hint_partial: "Translated lines are usable now; the rest keeps translating in the background and updates automatically.",
    hint_wait: "Subtitles aren't available until translation finishes, but you can already watch the video.",
    tx_title: "Subtitles ({total} lines)",
    tx_title_partial: "Subtitles ({n} / {total} translated)",
    status_processing: "Processing…",
    status_partial: "Partial subtitles available ({n} / {total} translated); the rest is translating in the background",
    status_done: "{via}  ·  {total} lines",
    resume_note: "  ·  Resumed from {time}",
    status_deleted: "Cache deleted",
    lib_running_pct: "Translating {pct}% — playable once finished",
    lib_stage: "{stage}…",
    lib_processing: "Processing",
    lib_paused: "Interrupted at {pct}% — click to resume",
    seen: " · watched to {time}",
    meta: "{via} · {count} lines · {date}",
    confirm_delete: "Delete the cache for \"{name}\"?\nSubtitles, translations and downloaded audio will be removed. Watching it again requires reprocessing (and calling Claude again).",
  },
};

// 後端回傳的錯誤訊息是中文；英文介面時對照翻譯，對不到的（多為 yt-dlp 等技術訊息）維持原文
const SERVER_MSG_EN = [
  [/無法從網址解析/, "Couldn't find a YouTube video ID in that URL"],
  [/這支影片正在處理中/, "This video is still being processed — try deleting it later"],
  [/找不到任務/, "Job not found"],
  [/字幕尚未準備好/, "Subtitles aren't ready yet"],
  [/找不到已完成的字幕/, "No finished subtitles to check"],
  [/找不到這支影片/, "Video not found"],
  [/不合法的影片 ID/, "Invalid video ID"],
  [/尚未設定 ANTHROPIC_API_KEY/, "No Claude API key is set yet — open Settings (top right) and enter one"],
  [/由環境變數 (\w+) 指定/, (m) => `Set by the ${m[1]} environment variable and can't be changed here`],
  [/API 金鑰格式不正確/, "The API key format is invalid (no spaces or line breaks)"],
  [/翻譯模型名稱格式不正確/, "The translation model name is invalid"],
  [/不支援的語音辨識模型/, "Unsupported speech-to-text model"],
  [/無法寫入設定檔/, "Couldn't write the settings file (.env) — check the data folder's permissions"],
  [/語音辨識沒有產生任何內容/, "Speech recognition produced no text"],
  [/音檔下載失敗/, "Audio download failed"],
  [/翻譯失敗：有 (\d+) 句/, (m) => `Translation failed: ${m[1]} lines were still untranslated after retries`],
];

function getLangPref() {
  try { const l = localStorage.getItem("lang"); return l === "zh-TW" || l === "en" ? l : "auto"; }
  catch (_) { return "auto"; }
}
function effLang() {
  const p = getLangPref();
  if (p !== "auto") return p;
  return /^zh/i.test(navigator.language || "") ? "zh-TW" : "en";
}
function setLangPref(l) {
  try { l === "auto" ? localStorage.removeItem("lang") : localStorage.setItem("lang", l); } catch (_) {}
}

function t(key, params) {
  const s = I18N[effLang()][key] ?? I18N["zh-TW"][key] ?? key;
  return params ? s.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? "") : s;
}

function serverMsg(msg) {
  if (effLang() === "zh-TW") return msg;
  for (const [re, out] of SERVER_MSG_EN) {
    const m = re.exec(msg);
    if (m) return typeof out === "function" ? out(m) : out;
  }
  return msg;
}

// 套用靜態文字：data-i18n（文字）、data-i18n-attr="屬性:key;屬性:key"
function applyStaticI18n() {
  const en = effLang() === "en";
  const root = document.documentElement;
  root.lang = en ? "en" : "zh-Hant";
  root.dataset.lang = en ? "en" : "zh"; // CSS 依此切換對應語系的標誌圖
  document.title = t("title");
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    el.dataset.i18nAttr.split(";").forEach((pair) => {
      const [attr, key] = pair.split(":");
      el.setAttribute(attr.trim(), t(key.trim()));
    });
  });
}
