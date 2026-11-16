// 字幕折行：一行放不下時，自己決定在哪裡換行，讓各行長度接近，並盡量斷在標點之後。
// 瀏覽器預設是「塞滿第一行，剩下的放第二行」，常變成第一行很長、第二行只有一兩個字。
// 純函式，沒有任何 DOM 依賴（寬度由呼叫端傳入的 measure 量），可以用 Node 直接測試。
(function (root) {
  const BREAK_AFTER = /[，、。；：！？,;:!?)）」』—…]/;    // 斷在這些標點之後最自然
  const NO_LINE_START = /[，、。；：！？,.;:!?%)）」』…]/;  // 不能出現在行首
  const NO_LINE_END = /[（(「『]/;                           // 不能出現在行尾
  const WORD = /[A-Za-z0-9_'’\-]/;                          // 英數字：同一個字不能從中間斷開
  const PUNCT_BONUS = 0.15; // 斷在標點後可以容許多大的長度差（佔全長的比例）

  // 所有可以換行的位置：[左邊字串, 右邊字串, 是否在標點之後]
  function candidates(text) {
    const out = [];
    for (let p = 1; p < text.length; p++) {
      const a = text[p - 1], b = text[p];
      let left, right;
      if (b === " ") { left = text.slice(0, p); right = text.slice(p + 1); }
      else if (a === " ") continue;                           // 空白已在上面處理
      else if (WORD.test(a) && WORD.test(b)) continue;        // 英文單字（含中文裡的 Docker）中間
      else if (NO_LINE_START.test(b) || NO_LINE_END.test(a)) continue;
      else if (!/[⺀-鿿가-힯豈-﫿＀-￯]/.test(a + b)) continue; // 非 CJK 只在空白斷
      else { left = text.slice(0, p); right = text.slice(p); }
      left = left.trimEnd(); right = right.trimStart();
      if (left && right) out.push([left, right, BREAK_AFTER.test(left[left.length - 1])]);
    }
    return out;
  }

  // 把 text 切成幾行，每行寬度（measure 量出來的）不超過 maxWidth，各行盡量一樣長
  function splitLines(text, maxWidth, measure) {
    text = String(text || "").trim();
    const total = measure(text);
    if (!text || total <= maxWidth || !(maxWidth > 0)) return [text];
    const n = Math.ceil(total / maxWidth);       // 至少需要幾行
    const nLeft = Math.floor(n / 2);              // 左半邊分到幾行（2 行時各 1 行）
    const target = total * nLeft / n;
    let best = null;
    for (const [left, right, punct] of candidates(text)) {
      const wl = measure(left), wr = measure(right);
      const fits = wl <= maxWidth * nLeft && wr <= maxWidth * (n - nLeft);
      const cost = Math.abs(wl - target) - (punct ? PUNCT_BONUS * total : 0) + (fits ? 0 : total * 10);
      if (!best || cost < best.cost) best = { cost, left, right };
    }
    if (!best) return [text]; // 沒有可以斷的地方（例如一個超長的網址）：交給瀏覽器
    return [...splitLines(best.left, maxWidth, measure), ...splitLines(best.right, maxWidth, measure)];
  }

  root.splitLines = splitLines;
  if (typeof module !== "undefined" && module.exports) module.exports = { splitLines };
})(typeof window !== "undefined" ? window : globalThis);
