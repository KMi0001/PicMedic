"""
utils/trash.py

Phase 2 "사진 정리" — 중복 파일을 완전 삭제하는 대신 앱 전용 임시 휴지통
폴더로 옮긴다("원본 보호" 원칙과 절충: 실수해도 파일이 진짜로 없어지지
않고 이 폴더에 남아있음). 옮길 때 원래 경로를 매니페스트(_MANIFEST_NAME)에
같이 남겨서, restore_from_trash()로 원래 위치에 되돌릴 수 있게 한다.
"""

from __future__ import annotations

import json
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
_MANIFEST_NAME = ".trash_manifest.json"


def trash_dir() -> Path:
    return TRASH_DIR


def _manifest_path() -> Path:
    return TRASH_DIR / _MANIFEST_NAME


def _load_manifest() -> dict[str, str]:
    manifest_path = _manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest: dict[str, str]) -> None:
    _manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def move_to_trash(path: str | Path) -> Path:
    """파일 하나를 임시 휴지통으로 옮기고 최종 경로를 반환한다.
    이름이 이미 있으면 원본을 덮어쓰지 않도록 번호를 붙인다. 나중에
    restore_from_trash()로 되돌릴 수 있게 원래 경로를 매니페스트에 남긴다."""
    path = Path(path)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)

    dest = TRASH_DIR / path.name
    counter = 1
    while dest.exists():
        dest = TRASH_DIR / f"{path.stem}_{counter}{path.suffix}"
        counter += 1

    shutil.move(str(path), str(dest))

    manifest = _load_manifest()
    manifest[dest.name] = str(path.resolve())
    _save_manifest(manifest)

    return dest


def restore_from_trash(path: str | Path) -> Path:
    """임시 휴지통에 있는 파일 하나를 원래 있던 폴더로 되돌린다.
    원래 경로를 모르면(매니페스트에 없음 — 이 기능이 생기기 전에 옮겨졌거나
    사용자가 직접 넣은 파일) ValueError. 원래 폴더가 사라졌으면 새로 만들고,
    같은 이름 파일이 이미 있으면 번호를 붙여 덮어쓰지 않는다."""
    path = Path(path)
    manifest = _load_manifest()
    original = manifest.get(path.name)
    if not original:
        raise ValueError(f"원래 위치를 알 수 없는 파일입니다: {path.name}")

    dest = Path(original)
    dest.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while dest.exists():
        dest = dest.parent / f"{Path(original).stem}_{counter}{Path(original).suffix}"
        counter += 1

    shutil.move(str(path), str(dest))

    del manifest[path.name]
    _save_manifest(manifest)

    return dest


def list_trash() -> list[Path]:
    """임시 휴지통에 있는 파일 목록(존재하지 않으면 빈 목록). 매니페스트
    파일 자체는 목록에 포함하지 않는다."""
    if not TRASH_DIR.exists():
        return []
    return sorted(
        (p for p in TRASH_DIR.iterdir() if p.is_file() and p.name != _MANIFEST_NAME),
        key=lambda p: p.name,
    )
