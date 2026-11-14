[English](README.en.md) | **繁體中文**

# 水管譯工 (TubeTran)

貼上 YouTube 網址即可播放影片，並顯示「原文＋繁體中文」雙語字幕。
同一個程式有兩種執行方式：**桌面應用程式**（直接執行）與**伺服器**（加上 `--server`）。

## 功能

- 優先下載 YouTube 字幕（人工字幕優先，其次自動字幕）；沒有字幕時，下載音檔並用本機 Whisper 辨識。
- 以 Claude API 翻譯成繁體中文（台灣用語），影片標題也一併翻譯。
- 字幕疊在影片上，全螢幕（按 `F`）時也看得到；可切換雙語／原文／譯文，並匯出 SRT／VTT。
- 翻譯到一半就能先使用已翻好的部分，其餘在背景繼續；處理進度以明顯的進度條呈現。
- 右側影片庫：列出已翻譯、翻譯中、中斷的影片，點擊即可重看，可刪除快取；記錄上次播放位置，下次接著看。
- 影片庫的搜尋與標籤：可搜尋標題（原文與譯名）與標籤；每支影片可加標籤（項目上的「＋ 標籤」，按 Enter 新增），清單上方的標籤列點一下即可篩選，可複選（需同時符合），並可與搜尋一起使用。
- 字幕檢查：合併重複、修正時序、補翻空白譯文（翻譯完成後自動跑一次，也可在清單項目旁手動重跑）。
- 淺色／深色主題，以及繁體中文／English 介面。兩者都是三態按鈕：自動（跟隨系統，預設）→ 手動切換。

## 運作流程

1. 以 `yt-dlp` 取得字幕（人工字幕優先，其次自動字幕）。
2. 若沒有字幕：下載音檔 → 本機 `faster-whisper` 語音辨識。
   （Claude API 不接受音檔輸入，因此語音轉文字由 Whisper 負責，Claude 只負責翻譯。）
3. 以 Claude API 分批翻譯成繁體中文，句數不對齊或譯文空白時自動重試；每批翻完就存檢查點，中斷後可從上次的位置接著翻。
4. 翻譯完成後自動檢查字幕，再存入快取。

結果快取在資料資料夾的 `cache/<video_id>/`，同一支影片不會重複下載或重複付費。

## 兩種模式

| | 桌面模式（預設） | 伺服器模式（`--server`） |
| --- | --- | --- |
| 啟動 | `python -m app` 或 `TubeTran.exe` | `python -m app --server` 或 `TubeTran.exe --server` |
| 介面 | 獨立視窗（使用系統的 WebView2） | 沒有視窗，用瀏覽器開 http://127.0.0.1:8000/ |
| 埠號 | 固定 `47321`（被占用時改用隨機埠），只接受本機連線 | 預設 `8000`，可用 `--host`、`--port` 修改 |
| 額外需求 | `desktop` 額外套件（pywebview）；Windows 需有 WebView2 | 無 |
| 結束 | 關閉視窗 | `Ctrl+C` |

兩種模式共用同一份後端與前端。桌面模式的後端是同一個程序裡的背景執行緒，視窗關閉、程序結束，不會留下孤兒程序。

> **警告：** 伺服器模式沒有任何身分驗證。若用 `--host 0.0.0.0` 讓區網連線，同一網路的任何人都能使用你的 Claude API key 進行翻譯。請只在可信任的網路使用。

## 安裝與執行

需要 [uv](https://docs.astral.sh/uv/)。專案釘選 Python 3.12（較新的版本可能缺少部分依賴的預編譯套件）。主要在 Windows 11 上開發與測試。

```powershell
uv sync --extra desktop              # 桌面模式需要；只用伺服器模式的話只需 uv sync
Copy-Item .env.example .env          # 然後編輯 .env，填入 ANTHROPIC_API_KEY

uv run python -m app                 # 桌面模式
uv run python -m app --server        # 伺服器模式：http://127.0.0.1:8000/
uv run python -m app --server --host 0.0.0.0 --port 9000   # 讓區網連線（請先閱讀上方警告）
uv run python -m app --help          # 查看所有參數
```

不需要預先安裝 `ffmpeg`（語音辨識使用 PyAV 內建的解碼程式庫）；若 `yt-dlp` 對特定影片提示需要它，再安裝即可（`scoop install ffmpeg`）。

## 設定

### `.env`

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key（必填） | — |
| `TRANSLATE_MODEL` | 翻譯用模型 | `claude-haiku-5-5` |
| `WHISPER_MODEL` | faster-whisper 模型大小 | `small` |
| `TRANSLATE_BATCH_SIZE` | 每批翻譯句數 | `50` |

有 CUDA 時 faster-whisper 會自動使用 GPU；首次使用會下載模型，大小依模型而定（從數十 MB 到數 GB）。

### 資料資料夾

`.env`、快取與桌面版的設定都放在「資料資料夾」，位置依序為：

1. 環境變數 `TRANTUBE_DATA_DIR`（若有設定）
2. 打包後的程式：`%LOCALAPPDATA%\TubeTran`
3. 開發時（直接從原始碼執行）：專案根目錄

資料夾內容：

| 項目 | 說明 |
| --- | --- |
| `.env` | 設定與 API key |
| `cache/<video_id>/` | 每支影片的快取：`subs.json`（原始字幕）、`translated.json`（最終結果）、`trans_partial.json`（翻譯檢查點，完成後刪除）、`progress.json`（播放位置）、`tags.json`（標籤，最多 10 個、每個 20 字）、`audio.*`（無字幕時的音檔）、`translated.pre-check.json`（手動檢查前的備份） |
| `webview/` | 桌面版的瀏覽器資料（主題與語言設定、cookie），已被 `.gitignore` 排除 |
| `tubetran.log` | 沒有主控台時（例如雙擊啟動）的輸出記錄 |

在影片庫按 ✕ 會刪除該影片整個 `cache/<video_id>/` 資料夾。

## 打包（Windows）

```powershell
uv sync --extra desktop
uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
```

成品在 `packaging/dist/TubeTran/TubeTran.exe`（資料夾版，需整個資料夾一起散布）。含本機 Whisper 的實測大小：資料夾約 266 MB，壓縮後約 109 MB，其中語音辨識相關的程式庫佔約 80%。`TubeTran.exe --selftest` 可檢查各依賴是否都被正確打包。

打包後的程式：直接執行是桌面模式，`--server` 為伺服器模式；從終端機執行時，輸出會顯示在該終端機。

## 專案結構

```
app/
  cli.py            命令列入口：桌面模式／--server
  config.py         設定與資料資料夾
  main.py           FastAPI 路由與靜態檔
  jobs.py           背景任務、快取、影片庫、播放進度
  services/         subtitles（字幕）、transcribe（Whisper）、translate（翻譯）、review（檢查）、export（SRT/VTT）
static/             前端（無建置步驟）：index.html、app.js、i18n.js、style.css、logo/
packaging/          PyInstaller 設定
tests/              pytest
tubetran.py         打包用的啟動入口
```

## 開發與測試

```powershell
uv run uvicorn app.main:app --reload --reload-dir app   # 開發用：改程式自動重載
uv run pytest
```

在 Windows 上結束 `--reload` 伺服器時，要連同子程序一起結束（`taskkill /PID <pid> /T /F`），否則舊程序可能繼續占用埠號，導致改過的程式沒有生效。

## 注意事項

- 介面語言只影響畫面文字；字幕與標題一律翻譯成繁體中文。
- 英文句子常被斷成片段，中文語序不同，所以少數片段的譯文不是字面對應，連續閱讀時語意仍然連貫。
- 無字幕影片的流程（下載音檔 → Whisper 辨識）目前只驗證過程式庫能載入，尚未用真實影片完整跑過。
- 翻譯會呼叫 Claude API 並產生費用；快取可避免重複付費，但「重新處理」或刪除快取後再看會重新翻譯。
- YouTube 常變動，若下載失敗請更新：`uv lock --upgrade-package yt-dlp && uv sync`。`yt-dlp` 可能提示找不到 JavaScript runtime（`deno`），目前不影響字幕與音檔下載；若遇到下載失敗可安裝它（`scoop install deno`）。
- 僅供個人使用，請遵守 YouTube 服務條款與影片版權。
