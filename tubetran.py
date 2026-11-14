"""打包用的啟動入口（PyInstaller 需要一個腳本檔）。開發時也可以直接 `python tubetran.py`。"""
from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
