# 自繪最大化鈕與 Windows 11 貼齊版面

🌐 繁體中文 ｜ [English](https://github.com/codemee/tubetran/blob/main/docs/en/windows-snap-layouts.md) ｜ [回到 README](https://github.com/codemee/tubetran/blob/main/README.md)

Windows 版的桌面視窗沒有系統標題列，視窗按鈕（最小化、最大化、關閉）是網頁自己畫的。這份文件說明怎麼讓滑鼠停在**最大化鈕**上時，Windows 11 的「貼齊版面」（Snap Layouts）選單照常彈出。

做法參考 [FEditor 的說明](https://github.com/codemee/feditor/blob/main/docs/windows-titlebar.md)（Rust／egui 版，沒有 WebView），再針對 WebView2 多做一層處理。

## 結果

| 項目 | 狀態 |
|---|---|
| 滑鼠停在最大化鈕：出現貼齊版面選單 | Windows 11 |
| 滑鼠停在最大化鈕：灰底高亮（選單出現期間維持） | 全部 Windows |
| 點最大化鈕：最大化／還原 | 全部 Windows |
| 在選單裡挑版面：視窗貼齊到該位置 | Windows 11 |
| 最大化鈕的 tooltip | 沒有（見下方「代價」） |

Windows 10 沒有貼齊版面選單，所以不啟用下面兩個機制，維持原本的行為。

## 為什麼需要兩個機制

Windows 11 要同時滿足兩個條件才會彈出選單：

| 條件 | 做法 |
|---|---|
| 1. 視窗要有**原生邊框**（只讓出標題列） | 攔 `WM_NCCALCSIZE`，保留系統算的左、右、下邊框，只把上緣收回客戶區 |
| 2. 滑鼠所在位置的 `WM_NCHITTEST` 要回報 `HTMAXBUTTON` | 在按鈕位置蓋一個透明子視窗，由它回報 |

第 1 項是從 Windows Terminal 的 `NonClientIslandWindow::_OnNcCalcSize` 學到的，不照做的話即使回報 `HTMAXBUTTON` 也不會出現選單。

## 第 2 項為什麼要蓋子視窗

FEditor 只要攔頂層視窗的 `WM_NCHITTEST` 就夠了，TubeTran 不行：

```
頂層視窗（WinForms，本行程）
└─ WinForms 控制項（本行程）
   └─ Chrome_WidgetWin_0（本行程）
      └─ Chrome_WidgetWin_1 → Chrome_RenderWidgetHostHWND（msedgewebview2.exe，另一個行程）
```

滑鼠在網頁上時，系統問的是最底層、另一個行程的 `Chrome_RenderWidgetHostHWND`，**不會問頂層視窗**，所以頂層視窗的 `WM_NCHITTEST` 根本收不到。回傳 `HTTRANSPARENT` 把命中測試穿透給父視窗也不行：這只對同一個執行緒的視窗有效。

解法：在最大化鈕的位置蓋一個**同行程、同執行緒**的透明子視窗（`TubeTranMaxButton`），放在 z 順序最上面。滑鼠在那個位置時，系統問的是它，由它回報 `HTMAXBUTTON`。

## 資料流

```
網頁 desktop.js                     後端 cli.py                     winctl.py
─────────────────                   ─────────────────               ─────────────────
量最大化鈕位置（CSS 像素）
× devicePixelRatio ─ set_max_button ─▶ 檢查數值、換成實體像素
                                      切到 UI 執行緒 ─────────────▶ 建立／移動覆蓋層（最上層）
                                                                    滑鼠移入 → WM_NCMOUSEMOVE
                                                                    （交還系統，貼齊版面靠它觸發）
灰底（.pointer-hover）◀─ evaluate_js ◀─ 背景執行緒 ◀─ 狀態回呼 ◀── 懸停／按下／離開
                                                                    點擊（WM_NCLBUTTONUP）
                                                                    → 送 WM_SYSCOMMAND 最大化／還原
```

- 按鈕位置改變（視窗縮放、換螢幕、頁面縮放）會重新回報；全螢幕時後端把覆蓋層藏起來，離開全螢幕再放回去。
- 覆蓋層是 `WS_EX_LAYERED` 加上 alpha = 1（約 0.4%），幾乎全透明但仍能被命中測試。
- 覆蓋層必須在**建立父視窗的 UI 執行緒**上建立（用 `window.native.Invoke`），它的訊息才有人處理。

## 覆蓋層上的滑鼠訊息

滑鼠在覆蓋層上時，訊息都變成非客戶區訊息，**網頁收不到**，所以自己處理：

| 訊息 | 處理 |
|---|---|
| `WM_NCHITTEST` | 回傳 `HTMAXBUTTON` |
| `WM_NCMOUSEMOVE` | 進入「懸停」狀態，開始每 60 毫秒確認游標還在鈕上；訊息**照常交還系統**，貼齊版面靠它觸發 |
| `WM_NCMOUSELEAVE` | 貼齊版面選單一彈出就會送來，但游標其實還在鈕上，所以只有游標真的離開才結束懸停 |
| `WM_NCLBUTTONDOWN` | 進入「按下」狀態，回傳 0（交給系統它會去畫不存在的標題列按鈕） |
| `WM_NCLBUTTONUP` | 在「按下」狀態放開才算點擊，送 `WM_SYSCOMMAND`（最大化時是 `SC_RESTORE`，否則 `SC_MAXIMIZE`） |

懸停與按下的外觀由後端用 `window.__maxButtonState(0|1|2)` 通知網頁。

## 連帶的改動

| 項目 | 原本 | 現在 |
|---|---|---|
| 最大化 | 自己把視窗鋪滿工作區、記住原本範圍 | 用系統的最大化（`ShowWindow(SW_MAXIMIZE)`） |
| 客戶區 | 涵蓋整個視窗（沒有邊框） | Windows 11：保留左、右、下的原生邊框（約 1 像素的細邊） |
| 最大化／全螢幕的客戶區 | 取與工作區的交集 | 不變 |

最大化改走系統的原因：保留原生邊框之後，自己鋪滿工作區的視窗在左、右、下會多出邊框的空隙；而且貼齊版面、Win+↑ 本來就是系統的最大化，兩條路合併後狀態只看 `IsZoomed`，不會不一致。

## 代價

- 滑鼠在最大化鈕上時網頁看不到游標，所以這顆鈕**沒有 tooltip**。
- 視窗上緣仍由網頁的縮放把手處理（客戶區涵蓋上緣，系統的縮放邊框只剩左、右、下）。

## 驗證

- **不動滑鼠確認命中**：`WindowFromPoint` 在按鈕中央應該回傳 `TubeTranMaxButton`，對它送 `WM_NCHITTEST` 應該回傳 9（`HTMAXBUTTON`）。
- **看選單**：把游標移到最大化鈕上停約 1 秒，用螢幕截圖（`CopyFromScreen`，`PrintWindow` 拍不到 DWM 疊上來的選單）確認選單出現、按鈕有灰底、移開後灰底消失。
- 測試：`tests/test_winctl.py`（客戶區的計算、位置回報的檢查與換算、全螢幕時藏起覆蓋層）。

## 參考

- [Microsoft Learn：Support snap layouts for desktop apps on Windows 11](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu)
- [Windows Terminal：`NonClientIslandWindow.cpp`](https://github.com/microsoft/terminal/blob/main/src/cascadia/WindowsTerminal/NonClientIslandWindow.cpp)（`_OnNcCalcSize`）
- 程式：[`tubetran/winctl.py`](https://github.com/codemee/tubetran/blob/main/tubetran/winctl.py)、[`tubetran/cli.py`](https://github.com/codemee/tubetran/blob/main/tubetran/cli.py)、[`tubetran/static/desktop.js`](https://github.com/codemee/tubetran/blob/main/tubetran/static/desktop.js)
