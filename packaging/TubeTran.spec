# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 設定：產生桌面程式 TubeTran（資料夾版）。
# 用法（在專案根目錄）：
#   uv run pyinstaller packaging/TubeTran.spec --noconfirm --clean --distpath packaging/dist --workpath packaging/build
#
# 同一個執行檔：直接執行 = 桌面模式；加 --server = 伺服器模式。
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = [("../tubetran/static", "tubetran/static")]  # 前端靜態檔（config.STATIC_DIR = 套件目錄/static）
datas += copy_metadata("tubetran")  # 讓打包後 importlib.metadata 讀得到版本號（tubetran/__init__.py 的 __version__）
binaries = []
hiddenimports = collect_submodules("uvicorn") + ["httptools", "websockets"]

# 本機語音辨識：faster-whisper 的資料檔（VAD 模型）與 ctranslate2 的原生程式庫
for pkg in ("faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["launch.py"],
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
    console=False,  # 視窗程式：不跳出主控台；命令列用法由 tubetran/cli.py 附著到父終端機
    icon=None if sys.platform == "darwin" else "../tubetran/static/logo/tubetran.ico",  # 執行檔（檔案總管、工作列）的圖示；視窗標題列則由 tubetran/cli.py 指定同一個檔案
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TubeTran")

# macOS：把資料夾版包成 TubeTran.app（之後再封裝成 .dmg）。圖示用 packaging/TubeTran.icns
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TubeTran.app",
        icon="TubeTran.icns",
        bundle_identifier="io.github.codemee.tubetran",
        info_plist={
            "CFBundleName": "TubeTran",
            "CFBundleDisplayName": "水管譯工 TubeTran",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # 網頁（YouTube 內嵌播放器）要連外網；本機後端只接受 127.0.0.1
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
