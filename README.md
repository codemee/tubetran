[English](README.en.md) | **繁體中文**

# trantube

本機網頁應用：貼上 YouTube 網址即可播放影片，並顯示「原文＋繁體中文」雙語字幕。

## 運作流程

1. 以 `yt-dlp` 取得字幕（人工字幕優先，其次自動字幕）。
2. 若沒有字幕：下載音檔 → 本機 `faster-whisper` 語音辨識。
   （Claude API 不接受音檔輸入，因此語音轉文字由 Whisper 負責，Claude 只負責翻譯。）
3. 以 Claude API 分批翻譯成繁體中文（台灣用語），句數不對齊時自動重試。
4. 前端以 YouTube IFrame Player 播放，字幕隨播放時間同步、可點擊跳轉，並可匯出 SRT / VTT。

結果會快取在 `cache/<video_id>/`，同一支影片不會重複下載或重複付費。

## 安裝與執行

```powershell
uv sync
Copy-Item .env.example .env   # 然後編輯 .env，填入 ANTHROPIC_API_KEY
uv run uvicorn app.main:app
```

開啟 http://localhost:8000 。系統需安裝 `ffmpeg`（`scoop install ffmpeg`）。

## 設定（`.env`）

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key（必填） | — |
| `TRANSLATE_MODEL` | 翻譯用模型 | `claude-haiku-5-5` |
| `WHISPER_MODEL` | faster-whisper 模型大小 | `small` |
| `TRANSLATE_BATCH_SIZE` | 每批翻譯句數 | `50` |

有 CUDA 時 faster-whisper 會自動使用 GPU；首次使用會下載模型。

## 測試

```powershell
uv run pytest
```

## 注意事項

- YouTube 常變動，若下載失敗請更新：`uv lock --upgrade-package yt-dlp && uv sync`。
- 僅供個人使用，請遵守 YouTube 服務條款與影片版權。
