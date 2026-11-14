"""打包用的啟動入口（PyInstaller 需要一個腳本檔）。開發時用 `uv run tubetran` 即可。"""
from tubetran.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
