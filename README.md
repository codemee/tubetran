[English](https://github.com/codemee/tubetran/blob/main/README.en.md) | **繁體中文**

# 水管譯工 (TubeTran)

貼上 YouTube 網址即可播放影片，並顯示「原文＋繁體中文」雙語字幕。
同一個程式有兩種執行方式：**桌面應用程式**（直接執行）與**伺服器**（加上 `--server`）。

## 功能

- 優先下載 YouTube 字幕（影片語言的人工字幕優先，其次自動字幕；他語的翻譯字幕不採用）；沒有字幕時，下載音檔並用本機 Whisper 辨識。
- 以 Claude API 翻譯成繁體中文（台灣用語），影片標題也一併翻譯。字幕以「一句一則」呈現：自動字幕原本斷在句子中間的片段，會先重組成完整的句子再翻譯，譯文不會錯位；整支影片的術語（例如 namespace、cgroup）前後譯法一致。
- 字幕疊在影片上，全螢幕時也看得到；太長的字幕會自動折成長度接近的兩行，盡量斷在標點之後。可切換雙語／原文／譯文，並匯出 SRT／VTT。
- 全螢幕：按播放器右下角（YouTube 字樣旁）的全螢幕鈕，或按 `F`。桌面版點過影片之後按 `F` 也有效（瀏覽器模式要先點一下影片外面，才收得到 `F`）。全螢幕鈕會跟著 YouTube 的控制列一起顯示與隱藏：桌面版直接偵測控制列右下角的「YouTube」字樣在不在；瀏覽器模式偵測不到，滑鼠在播放區內就一直顯示。
- 翻譯到一半就能先使用已翻好的部分，其餘在背景繼續；處理進度以明顯的進度條呈現。
- 右側影片庫：列出已翻譯、翻譯中、中斷的影片，點擊即可重看，可刪除快取（處理中的影片按 ✕ 會取消處理並清除）；記錄上次播放位置，下次接著看。每個項目與播放器標題下方都有「在 YouTube 開啟」連結，方便回到 YouTube 看留言、相關影片（桌面版會用系統預設瀏覽器開啟）。
- 影片庫的搜尋與標籤：可搜尋標題（原文與譯名）與標籤；每支影片可加標籤（項目上的「＋ 標籤」，按 Enter 新增），清單上方的標籤列點一下即可篩選，可複選（需同時符合），並可與搜尋一起使用。標籤列最前面固定有「無標籤」，點了只列出還沒加標籤的影片（和一般標籤互斥）；標籤很多時只顯示一行，最後面的「更多 +N」可展開全部，「清除篩選」固定在右側。
- 影片庫項目上的按鈕（滑鼠移到項目上才出現）：

  | 按鈕 | 作用 |
  |---|---|
  | ↗ 在 YouTube 開啟 | 回到 YouTube 看留言、相關影片 |
  | ↻ 重新處理 | 丟掉目前的翻譯，重新取得字幕並以整句重新翻譯（會再呼叫 Claude）；觀看進度與標籤保留。舊版翻譯的影片可以用它改成一句一則 |
  | ☑ 檢查字幕 | 合併重複、修正時序、補翻空白譯文（翻譯完成後也會自動跑一次） |
  | ✕ 刪除 | 刪除快取；處理中的影片則是取消處理並清除 |
- 淺色／深色主題，以及繁體中文／English 介面。兩者都是三態按鈕：自動（跟隨系統，預設）→ 手動切換。

## 運作流程

1. 用 `yt-dlp` 取得字幕（影片語言的人工字幕優先，其次自動字幕）。
2. 若沒有字幕：下載音檔 → 本機 `faster-whisper` 語音辨識。
   （Claude API 不接受音檔輸入，因此語音轉文字由 Whisper 負責，Claude 只負責翻譯。）
3. 把斷在句子中間的字幕片段重組成完整的句子（太長的句子在逗號處切開）。
4. 讀完整支影片整理術語表，決定專有名詞的統一譯法。
5. 以 Claude API 分批翻譯成繁體中文；每批都附上術語表與前後幾句當參考，句數不對齊或譯文空白時自動重試。每批翻完就存檢查點，中斷後可從上次的位置接著翻。
6. 翻譯完成後自動檢查字幕，再存入快取。

```
字幕片段（自動字幕依說話節奏斷行）            一句一則（翻譯與顯示的單位）
  8:54  carefully sharing a folder across mount    8:52  When Docker says volume mount, that is carefully
  8:56  views. When Docker says memory limit,  ──▶        sharing a folder across mount views.
  8:58  that is a Cgroup. When a container has     8:57  When Docker says memory limit, that is a Cgroup.
```

結果快取在資料資料夾的 `cache/<video_id>/`，同一支影片不會重複下載或重複付費。

## 兩種模式

| | 桌面模式（預設） | 伺服器模式（`--server`） |
| --- | --- | --- |
| 啟動 | `python -m tubetran` 或 `TubeTran.exe` | `python -m tubetran --server` 或 `TubeTran.exe --server` |
| 介面 | 獨立的無框視窗（Windows 用系統的 WebView2，macOS 用系統的 WKWebView）；Windows 上沒有系統標題列，視窗按鈕畫在頁首右上角（見下方說明） | 沒有視窗，用瀏覽器開 http://127.0.0.1:8000/ |
| 埠號 | 固定 `47321`（被占用時改用隨機埠），只接受本機連線 | 預設 `8000`，可用 `--host`、`--port` 修改 |
| 額外需求 | `desktop` 額外套件（pywebview）；Windows 需有 WebView2 | 無 |
| 結束 | 關閉視窗 | `Ctrl+C` |

**桌面模式的視窗（Windows）：** 沒有系統標題列與邊框，頁首右上角有自製的最小化、最大化／還原、關閉按鈕。拖曳頁首空白處或左上角圖示可以移動視窗，雙擊則最大化／還原（最大化時鋪滿螢幕工作區，不會蓋住工作列），視窗四邊與四角可以拖曳縮放。不想要這個外觀的話，加上 `--native-titlebar` 就會改用系統標題列。其他作業系統目前一律使用系統標題列（無框視窗只在 Windows 上實作並測試過）。macOS 上全螢幕是讓播放區鋪滿視窗並讓整個視窗進入全螢幕；全螢幕鈕只能靠游標位置估計，滑鼠停止約 4 秒後隱藏，不像 Windows 能直接偵測 YouTube 控制列；桌面版點過影片後的 `F` 快捷鍵也只有 Windows 支援（macOS 請先點一下影片外面，或直接按全螢幕鈕）。

兩種模式共用同一份後端與前端。桌面模式的後端是同一個程序裡的背景執行緒，視窗關閉、程序結束，不會留下孤兒程序。

> **警告：** 伺服器模式沒有任何身分驗證。若用 `--host 0.0.0.0` 讓區網連線，同一網路的任何人都能使用你的 Claude API key 進行翻譯。請只在可信任的網路使用。

## 安裝與執行

需要 [uv](https://docs.astral.sh/uv/)。Python 版本限定 3.12–3.13（較新的版本可能缺少部分依賴的預編譯套件）。主要在 Windows 11 上開發與測試；macOS 也可以執行（Apple 晶片可下載預先打包的 App，或從原始碼、`uv tool install` 執行）。

### 下載 Windows 執行檔（最簡單）

到 [Releases](https://github.com/codemee/tubetran/releases) 下載 `TubeTran-vX.Y.Z-windows-x64.zip`，解壓縮後執行 `TubeTran.exe`（桌面模式；加上 `--server` 則是伺服器模式）。不需要安裝 Python。第一次執行時，在右上角的設定面板輸入 Claude API 金鑰即可。

> 執行檔沒有數位簽章，Windows SmartScreen 可能會警告；選「其他資訊 → 仍要執行」。
>
> 如果桌面視窗打不開、出現 `Failed to resolve Python.Runtime.Loader.Initialize` 之類的錯誤（0.1.1 以前的版本會遇到），是因為 Windows 把從網路下載的檔案標記成「已封鎖」。請對 ZIP 檔按右鍵 →「內容」→ 勾選「解除封鎖」，再重新解壓縮；或在 PowerShell 執行 `Get-ChildItem "TubeTran 資料夾" -Recurse | Unblock-File`。新版程式啟動時會自動清除這個標記。每個版本的 ZIP 由 GitHub Actions 自動建置，內容與 PyPI 上同一版本相同。

### 下載 macOS App（Apple 晶片）

到 [Releases](https://github.com/codemee/tubetran/releases) 下載 `TubeTran-vX.Y.Z-macos-arm64.dmg`，開啟後把 TubeTran 拖進「應用程式」。只提供 Apple 晶片（M 系列）版，沒有 Intel 版。

> App 沒有簽章也沒有公證，第一次開啟時 macOS 會擋下。請在「應用程式」裡對 TubeTran 按右鍵 →「打開」，或到「系統設定 → 隱私權與安全性」按「仍要打開」；也可以執行 `xattr -dr com.apple.quarantine /Applications/TubeTran.app`。

### 用 `uv tool install` 從 PyPI 安裝

```powershell
uv tool install --python 3.12 "tubetran[desktop]"   # 只用伺服器模式的話可省略 [desktop]

tubetran --help                      # 查看所有參數
tubetran --server                    # 伺服器模式：http://127.0.0.1:8000/
tubetran                             # 桌面模式（需要 [desktop]）
```

> **一定要加 `--python 3.12`（或 `3.13`）。** `uv tool install` 預設使用電腦上找到的 Python；如果那是比較新的版本（例如 3.14 以上），語音辨識需要的 `onnxruntime` 還沒有對應的套件，會安裝失敗（`No solution found … onnxruntime … no wheels with a matching Python ABI tag`）。加上參數後，uv 會自動下載需要的 Python。

從原始碼或 GitHub 安裝：

```powershell
uv tool install --python 3.12 ".[desktop]"           # 在專案資料夾執行
uv tool install --python 3.12 "tubetran[desktop] @ git+https://github.com/codemee/tubetran.git"
```

第一次執行時，在網頁右上角的[設定面板](#設定面板)輸入 Claude API 金鑰即可（沒有金鑰時會自動展開）；也可以改設同名的環境變數 `ANTHROPIC_API_KEY`。更新用 `uv tool upgrade tubetran`（從本機資料夾安裝的話，改完程式後用 `uv tool install --python 3.12 --reinstall ".[desktop]"`），移除用 `uv tool uninstall tubetran`。

### 從原始碼執行（開發用）

```powershell
uv sync --extra desktop              # 桌面模式需要；只用伺服器模式的話只需 uv sync

# 啟動後在網頁的設定面板輸入 API 金鑰；也可以改用環境變數 ANTHROPIC_API_KEY

uv run python -m tubetran                 # 桌面模式
uv run python -m tubetran --server        # 伺服器模式：http://127.0.0.1:8000/
uv run python -m tubetran --server --host 0.0.0.0 --port 9000   # 讓區網連線（請先閱讀上方警告）
uv run python -m tubetran --help          # 查看所有參數
```

不需要預先安裝 `ffmpeg`（語音辨識使用 PyAV 內建的解碼程式庫）；若 `yt-dlp` 對特定影片提示需要它，再安裝即可（`scoop install ffmpeg`）。

## 設定

### 設定面板

頁首右上角、語言鈕左邊的設定鈕會展開設定面板，可以調整：

- **Claude API 金鑰：** 只顯示頭尾各兩碼，中間以 `*` 取代；完整金鑰不會回傳到瀏覽器。要更換就直接貼上新的金鑰。沒有金鑰時程式照常啟動，並自動展開面板請你輸入。
- **翻譯模型：** 選項是向 Anthropic 查詢「這把金鑰實際可用」的模型清單（需要有效金鑰）。
- **語音辨識（STT）模型：** 選項是 faster-whisper 官方支援的模型清單（取自它的 `available_models()`），只在影片沒有字幕時使用。

面板最下方顯示程式版本（例如 `TubeTran v0.1.9`），點一下可前往 GitHub 的發行版本；命令列也可用 `tubetran --version` 查詢。

按「儲存」後寫入資料資料夾的 `settings.json`，對之後開始的任務立即生效，不必重啟。

> **金鑰是以明文存放的。** `settings.json` 內含你的 API 金鑰，沒有加密，也沒有使用系統的憑證儲存區；在 macOS／Linux 上檔案權限會限定只有本人可讀寫。請不要把資料資料夾分享或上傳到任何地方。從原始碼執行時資料資料夾就是專案根目錄，`settings.json` 已被 `.gitignore` 排除。

> **優先順序（高 → 低）：** ① 作業系統的環境變數 ② 設定面板儲存的 `settings.json` ③ 舊式的 `.env`（只讀，程式不再寫入；為了相容舊版而保留）④ 內建預設值。如果 `ANTHROPIC_API_KEY`、`TRANSLATE_MODEL` 或 `WHISPER_MODEL` 在啟動前就已經由環境變數指定，面板會把該欄位鎖住並標示來源（在面板改也不會生效）；要改請修改環境變數，或移除它之後再用面板設定。

### 環境變數

下列變數可用環境變數（或舊式 `.env`）設定；金鑰與兩個模型平常直接用設定面板即可。

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key（必填） | — |
| `TRANSLATE_MODEL` | 翻譯用模型 | `claude-haiku-5-5` |
| `WHISPER_MODEL` | faster-whisper 模型大小 | `small` |
| `TRANSLATE_BATCH_SIZE` | 每批翻譯句數 | `50` |

有 CUDA 時 faster-whisper 會自動使用 GPU；首次使用會下載模型，大小依模型而定（從數十 MB 到數 GB）。

### 資料資料夾

`settings.json`、快取與桌面版的設定都放在「資料資料夾」，位置依序為：

1. 環境變數 `TUBETRAN_DATA_DIR`（若有設定）
2. 開發時（直接從原始碼資料夾執行）：專案根目錄
3. 其他情況（`uv tool install` 安裝、打包後的程式）：使用者資料目錄 — Windows 是 `%LOCALAPPDATA%\TubeTran`，macOS 是 `~/Library/Application Support/TubeTran`，Linux 是 `$XDG_DATA_HOME/TubeTran`（未設定時為 `~/.local/share/TubeTran`）

資料夾內容：

| 項目 | 說明 |
| --- | --- |
| `settings.json` | 設定面板儲存的設定：API 金鑰（明文）、翻譯模型、STT 模型 |
| `.env` | （選用，舊式）只讀；有的話作為最低優先順序的設定來源 |
| `cache/<video_id>/` | 每支影片的快取：`subs.json`（字幕：原始片段與重組後的整句）、`glossary.json`（術語表）、`translated.json`（最終結果）、`trans_partial.json`（翻譯檢查點，完成後刪除）、`progress.json`（播放位置）、`tags.json`（標籤，最多 10 個、每個 20 字）、`audio.*`（無字幕時的音檔）、`translated.pre-check.json`（手動檢查前的備份） |
| `webview/` | 桌面版的瀏覽器資料（主題與語言設定、cookie），已被 `.gitignore` 排除 |
| `tubetran.log` | 沒有主控台時（例如雙擊啟動）的輸出記錄 |

在影片庫按 ✕ 會刪除該影片整個 `cache/<video_id>/` 資料夾。影片還在處理中時，按 ✕ 會先要求背景任務取消（約在目前這一步，例如一批翻譯完成後結束），任務結束時自己清除快取，卡片會顯示「取消中…」後消失；已呼叫 Claude 翻譯的部分無法退費。

## 打包（Windows）

```powershell
uv sync --extra desktop
uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
```

成品在 `packaging/dist/TubeTran/TubeTran.exe`（資料夾版，需整個資料夾一起散布）。含本機 Whisper 的實測大小：資料夾約 266 MB，壓縮後約 109 MB，其中語音辨識相關的程式庫佔約 80%。`TubeTran.exe --selftest` 可檢查各依賴是否都被正確打包。

打包後的程式：直接執行是桌面模式，`--server` 為伺服器模式；從終端機執行時，輸出會顯示在該終端機。

### 打包（macOS）

同一份 spec 在 macOS 上會多產生一個 App：

```bash
uv sync --extra desktop
uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
```

成品是 `packaging/dist/TubeTran.app`（約 200 MB），圖示是 `packaging/TubeTran.icns`。`TubeTran.app/Contents/MacOS/TubeTran --selftest` 可檢查依賴是否都被正確打包。要做成 DMG：把 App 與指向 `/Applications` 的捷徑放進同一個資料夾，再用 `hdiutil create -volname TubeTran -srcfolder <資料夾> -format UDZO TubeTran.dmg`（CI 的做法見 `release.yml` 的 `dmg` 工作）。

## 專案結構

```
tubetran/
  cli.py            命令列入口：桌面模式／--server
  winctl.py         桌面模式（Windows）無框視窗的最大化與邊緣縮放
  config.py         設定與資料資料夾
  settings.py       設定面板的儲存、金鑰遮罩、模型清單
  main.py           FastAPI 路由與靜態檔
  jobs.py           背景任務、快取、影片庫、播放進度
  services/         subtitles（字幕）、sentences（片段重組成整句）、transcribe（Whisper）、translate（翻譯、術語表）、review（檢查）、export（SRT/VTT）
  static/           前端（無建置步驟）：index.html、app.js、settings.js、desktop.js、i18n.js、linebreak.js（字幕折行）、style.css、logo/
packaging/          PyInstaller 設定與啟動入口（launch.py）
tests/              pytest
```

## 開發與測試

```powershell
uv run uvicorn tubetran.main:app --reload --reload-dir tubetran   # 開發用：改程式自動重載
uv run pytest
```

在 Windows 上結束 `--reload` 伺服器時，要連同子程序一起結束（`taskkill /PID <pid> /T /F`），否則舊程序可能繼續占用埠號，導致改過的程式沒有生效。

### 發布新版本

發布是全自動的：推送 `v*` 標籤後，[GitHub Actions](https://github.com/codemee/tubetran/blob/main/.github/workflows/release.yml) 會依序執行測試、建置 Python 套件並**發布到 PyPI**、在 Windows 上打包 `TubeTran.exe` 並壓成 **ZIP**、在 macOS（Apple 晶片）上打包 App 並封裝成 **DMG**、建立 GitHub Release 並附上這些檔案。

```powershell
# 1. 修改 pyproject.toml 的 version，更新鎖定檔；寫好這一版的重點 release-notes/v0.2.0.md（中英文），一起提交
uv lock
git add release-notes/v0.2.0.md
git commit -am "版本 0.2.0"
# 2. 打上與版本相同的標籤並推送（標籤必須是 v + pyproject.toml 的版本，否則流程會停下來）
git tag v0.2.0
git push origin main v0.2.0
```

**Release 說明：** 最前面是 `release-notes/<標籤>.md` 的「本版重點」（這一版新增、修正了什麼，使用者看得懂的描述，中英文並列），之後只附 GitHub 自動產生的變更記錄連結；下載與安裝方式寫在 README，不在每個 Release 裡重複。缺少該檔案時，流程會在最前面的測試階段就停下來，不會等到 PyPI 發布後才發現。

**試跑：** 到 GitHub 的 Actions → Release → Run workflow，只會測試與建置，不會發布。

**PyPI 只需要設定一次：** 到 [pypi.org/manage/account/publishing](https://pypi.org/manage/account/publishing/) 新增一個「pending publisher」，填入 PyPI Project name `tubetran`、Owner `codemee`、Repository name `tubetran`、Workflow name `release.yml`、Environment name `pypi`（受信任的發布者，不需要保存任何金鑰）。或者改在 GitHub 的 Settings → Secrets 設定 `PYPI_API_TOKEN`。PyPI 的版本號發布後就不能重複使用，所以發布前請先用試跑確認。

## 注意事項

- 介面語言只影響畫面文字；字幕與標題一律翻譯成繁體中文。
- 舊版翻譯的影片仍是「一段一則」，可能有譯文錯位；在影片庫按 ↻ 重新處理即可改成一句一則（會重新呼叫 Claude）。
- 無字幕影片的流程（下載音檔 → Whisper 辨識）目前只驗證過程式庫能載入，尚未用真實影片完整跑過。
- 翻譯會呼叫 Claude API 並產生費用；快取可避免重複付費，但「重新處理」或刪除快取後再看會重新翻譯。
- YouTube 常變動，若下載失敗請更新：`uv lock --upgrade-package yt-dlp && uv sync`。`yt-dlp` 可能提示找不到 JavaScript runtime（`deno`），目前不影響字幕與音檔下載；若遇到下載失敗可安裝它（`scoop install deno`）。
- 僅供個人使用，請遵守 YouTube 服務條款與影片版權。

## 授權

本專案以 [GNU 通用公共授權條款第 3 版或（由你選擇）更新版本（GPL-3.0-or-later）](https://github.com/codemee/tubetran/blob/main/LICENSE)釋出。你可以自由使用、研究、修改與散布，但散布修改版（包含打包成執行檔）時，必須同樣以 GPL 公開原始碼。
