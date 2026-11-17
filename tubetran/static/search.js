// 字幕搜尋：把搜尋字串與選項（不分大小寫、完整單字、規則表達式）轉成 RegExp，找出每一則字幕裡命中的範圍，
// 再把命中的地方包上 <mark>。純函式，沒有任何 DOM 依賴，可以用 Node 直接測試。
(function (root) {
  // 「完整單字」的邊界：只看英數字（含常見的拉丁字母）。中文、日文沒有空白分詞，整句都算一個「字」就永遠找不到，
  // 所以中日文的字不當成單字的一部分：搜尋「容器」時，「Docker 容器」「容器化」都找得到。
  const WORD_CHAR = "[A-Za-z0-9_\\u00C0-\\u024F]";

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // 回傳 { re } 或 { error }（規則表達式寫錯）；搜尋字串是空的回傳 null
  function buildSearch(query, opts = {}) {
    if (!query) return null;
    let src = opts.regex ? query : escapeRe(query);
    if (opts.wholeWord) src = `(?<!${WORD_CHAR})(?:${src})(?!${WORD_CHAR})`;
    try {
      return { re: new RegExp(src, "gu" + (opts.ignoreCase ? "i" : "")) };
    } catch (e) {
      return { error: e.message };
    }
  }

  // 一段文字裡所有命中的範圍 [[開始, 結束], ...]。長度 0 的命中（例如 /a*/）略過，免得無窮迴圈、也沒東西可標
  function findRanges(text, re) {
    const out = [];
    if (!text || !re) return out;
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m[0].length === 0) { re.lastIndex += m.index < text.length && text.codePointAt(m.index) > 0xffff ? 2 : 1; continue; }
      out.push([m.index, m.index + m[0].length]);
    }
    return out;
  }

  // 把命中的範圍包上 <mark>；其餘文字用 esc 跳脫。mark(k) 回傳第 k 個命中的屬性字串（例如 data-m、class）
  function highlight(text, ranges, esc, mark = () => "") {
    let html = "", at = 0;
    ranges.forEach(([s, e], k) => {
      html += esc(text.slice(at, s)) + `<mark${mark(k)}>${esc(text.slice(s, e))}</mark>`;
      at = e;
    });
    return html + esc(text.slice(at));
  }

  const api = { buildSearch, findRanges, highlight };
  root.SubSearch = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
