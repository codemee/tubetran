"""水管譯工 (TubeTran)。"""
from importlib.metadata import PackageNotFoundError, version as _dist_version

try:
    # 版本號的唯一來源是 pyproject.toml；安裝後（含 uv sync 的可編輯安裝、PyInstaller 打包時附帶的 metadata）從這裡讀
    __version__ = _dist_version("tubetran")
except PackageNotFoundError:  # 直接從原始碼資料夾執行、又沒有安裝時
    __version__ = "dev"
