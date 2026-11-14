# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 設定：產生桌面程式 TubeTran（資料夾版）。
# 用法（在專案根目錄）：
#   uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
#
# 同一個執行檔：直接執行 = 桌面模式；加 --server = 伺服器模式。
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("../static", "static")]  # 前端靜態檔
binaries = []
hiddenimports = collect_submodules("uvicorn") + ["httptools", "websockets"]

# 本機語音辨識：faster-whisper 的資料檔（VAD 模型）與 ctranslate2 的原生程式庫
for pkg in ("faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["../tubetran.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "_pytest", "tkinter", "matplotlib", "IPython", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TubeTran",
    console=False,  # 視窗程式：不跳出主控台；命令列用法由 app/cli.py 附著到父終端機
    icon="../static/logo/tubetran.ico",  # 執行檔（檔案總管、工作列）的圖示；視窗標題列則由 app/cli.py 指定同一個檔案
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TubeTran")
