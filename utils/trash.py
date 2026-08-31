"""
utils/trash.py

Phase 2 "사진 정리" — 중복 파일을 완전 삭제하는 대신 앱 전용 임시 휴지통
폴더로 옮긴다("원본 보호" 원칙과 절충: 실수해도 파일이 진짜로 없어지지
않고 이 폴더에 남아있음). 복원/영구 삭제 기능은 아직 없음 — 필요하면
폴더를 직접 열어서 처리한다(gui/trash_screen.py가 폴더 열기를 제공).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 실행 파일: __file__은 임시 압축해제 폴더를 가리키므로
    # 실제 .exe 옆에 남도록 sys.executable 기준으로 잡는다 (utils/logger.py와 동일 방식).
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

TRASH_DIR = _BASE_DIR / "임시휴지통"


def trash_dir() -> Path:
    return TRASH_DIR


def move_to_trash(path: str | Path) -> Path:
    """파일 하나를 임시 휴지통으로 옮기고 최종 경로를 반환한다.
    이름이 이미 있으면 원본을 덮어쓰지 않도록 번호를 붙인다."""
    path = Path(path)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)

    dest = TRASH_DIR / path.name
    counter = 1
    while dest.exists():
        dest = TRASH_DIR / f"{path.stem}_{counter}{path.suffix}"
        counter += 1

    shutil.move(str(path), str(dest))
    return dest


def list_trash() -> list[Path]:
    """임시 휴지통에 있는 파일 목록(존재하지 않으면 빈 목록)."""
    if not TRASH_DIR.exists():
        return []
    return sorted((p for p in TRASH_DIR.iterdir() if p.is_file()), key=lambda p: p.name)
