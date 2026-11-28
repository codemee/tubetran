# The custom maximize button and Windows 11 Snap Layouts

🌐 [繁體中文](https://github.com/codemee/tubetran/blob/main/docs/zh-TW/windows-snap-layouts.md) ｜ English ｜ [Back to the README](https://github.com/codemee/tubetran/blob/main/README.en.md)

The Windows desktop window has no system title bar; the window buttons (minimize, maximize, close) are drawn by the web page. This page explains how the Windows 11 **Snap Layouts** flyout still appears when the pointer rests on the **maximize button**.

The approach follows [FEditor's write-up](https://github.com/codemee/feditor/blob/main/docs/windows-titlebar.md) (Rust / egui, no WebView), with one extra layer for WebView2.

## Result

| Item | Status |
|---|---|
| Pointer on the maximize button: Snap Layouts flyout | Windows 11 |
| Pointer on the maximize button: grey highlight (kept while the flyout is open) | All Windows |
| Click the maximize button: maximize / restore | All Windows |
| Pick a layout in the flyout: the window snaps there | Windows 11 |
| Tooltip on the maximize button | None (see "Trade-offs") |

Windows 10 has no Snap Layouts flyout, so the two mechanisms below are not enabled there and behavior is unchanged.

## Why two mechanisms

Windows 11 shows the flyout only when both conditions hold:

| Condition | How |
|---|---|
| 1. The window keeps its **native frame** (only the title bar is given up) | Intercept `WM_NCCALCSIZE`: keep the system's left, right and bottom borders, take only the top edge back into the client area |
| 2. `WM_NCHITTEST` at the pointer position reports `HTMAXBUTTON` | Put a transparent child window over the button and let it report it |

Condition 1 comes from Windows Terminal's `NonClientIslandWindow::_OnNcCalcSize`; without it the flyout does not appear even if `HTMAXBUTTON` is reported.

## Why a child window for condition 2

Intercepting `WM_NCHITTEST` on the top-level window is enough for FEditor but not for TubeTran:

```
Top-level window (WinForms, this process)
└─ WinForms control (this process)
   └─ Chrome_WidgetWin_0 (this process)
      └─ Chrome_WidgetWin_1 → Chrome_RenderWidgetHostHWND (msedgewebview2.exe, another process)
```

With the pointer over the page, the system asks the innermost window, which lives in another process, **never the top-level window**, so the top-level `WM_NCHITTEST` is not called. Returning `HTTRANSPARENT` to pass the hit test through to the parent does not help either: it only works for windows on the same thread.

The fix: put a transparent child window (`TubeTranMaxButton`) of **the same process and thread** over the maximize button, at the top of the z-order. With the pointer there the system asks it, and it reports `HTMAXBUTTON`.

## Data flow

```
Page desktop.js                     Backend cli.py                  winctl.py
─────────────────                   ─────────────────               ─────────────────
measure the button (CSS px)
× devicePixelRatio ─ set_max_button ─▶ validate, convert to physical px
                                      switch to the UI thread ────▶ create / move the overlay (topmost)
                                                                    pointer enters → WM_NCMOUSEMOVE
                                                                    (passed to the system: triggers the flyout)
grey fill (.pointer-hover) ◀─ evaluate_js ◀─ worker thread ◀─ state callback ◀── hover / press / leave
                                                                    click (WM_NCLBUTTONUP)
                                                                    → send WM_SYSCOMMAND maximize / restore
```

- The position is re-reported when it changes (resize, another monitor, page zoom). In fullscreen the backend hides the overlay and puts it back afterwards.
- The overlay is `WS_EX_LAYERED` with alpha = 1 (about 0.4%): practically invisible but still hit-testable.
- The overlay must be created on **the UI thread that owns the parent window** (via `window.native.Invoke`), or nobody processes its messages.

## Mouse messages on the overlay

Over the overlay, mouse messages become non-client messages and **the page never sees them**, so they are handled here:

| Message | Handling |
|---|---|
| `WM_NCHITTEST` | Return `HTMAXBUTTON` |
| `WM_NCMOUSEMOVE` | Enter "hover", start checking every 60 ms that the cursor is still on the button; the message is **passed to the system as usual**, which is what triggers the flyout |
| `WM_NCMOUSELEAVE` | Arrives as soon as the flyout opens although the cursor is still on the button, so hover ends only when the cursor really left |
| `WM_NCLBUTTONDOWN` | Enter "pressed", return 0 (the system would draw caption buttons that do not exist) |
| `WM_NCLBUTTONUP` | A release while "pressed" counts as a click: send `WM_SYSCOMMAND` (`SC_RESTORE` when maximized, otherwise `SC_MAXIMIZE`) |

The backend tells the page the hover / pressed look through `window.__maxButtonState(0|1|2)`.

## Side effects of the change

| Item | Before | Now |
|---|---|---|
| Maximize | Fill the work area ourselves and remember the old rectangle | The system maximize (`ShowWindow(SW_MAXIMIZE)`) |
| Client area | The whole window (no frame) | Windows 11: keeps the native left, right and bottom border (a thin line of about 1 px) |
| Client area when maximized / fullscreen | Intersection with the work area | Unchanged |

Maximize moved to the system because, with the native frame kept, a window we fill to the work area would leave frame-sized gaps on the left, right and bottom; and Snap Layouts and Win+↑ are system maximizes anyway. With one path the state is just `IsZoomed`, so it cannot disagree.

## Trade-offs

- The page cannot see the pointer over the maximize button, so that button has **no tooltip**.
- The top edge is still resized by the page's resize handles (the client area covers the top edge, so the system's resize border exists only on the left, right and bottom).

## Verifying

- **Hit test without moving the mouse:** `WindowFromPoint` at the button centre should return `TubeTranMaxButton`, and sending it `WM_NCHITTEST` should return 9 (`HTMAXBUTTON`).
- **Seeing the flyout:** rest the cursor on the maximize button for about a second and capture the screen with `CopyFromScreen` (`PrintWindow` cannot capture the flyout DWM draws on top). Check that the flyout appears, the button is grey, and the grey disappears after moving away.
- Tests: `tests/test_winctl.py` (client-area calculation, validation and conversion of the reported position, hiding the overlay in fullscreen).

## References

- [Microsoft Learn: Support snap layouts for desktop apps on Windows 11](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu)
- [Windows Terminal: `NonClientIslandWindow.cpp`](https://github.com/microsoft/terminal/blob/main/src/cascadia/WindowsTerminal/NonClientIslandWindow.cpp) (`_OnNcCalcSize`)
- Code: [`tubetran/winctl.py`](https://github.com/codemee/tubetran/blob/main/tubetran/winctl.py), [`tubetran/cli.py`](https://github.com/codemee/tubetran/blob/main/tubetran/cli.py), [`tubetran/static/desktop.js`](https://github.com/codemee/tubetran/blob/main/tubetran/static/desktop.js)
