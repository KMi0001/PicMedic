"""
utils/assets.py

assets/ 폴더 파일(아이콘 등)의 실제 경로를 구한다.
개발 실행(python main.py)과 PyInstaller 빌드 실행 파일 양쪽에서 동작해야 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path


def asset_path(name: str) -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # PyInstaller가 풀어놓은 임시 경로
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / "assets" / name)
