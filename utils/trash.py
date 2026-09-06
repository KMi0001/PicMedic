"""
utils/trash.py

Phase 2 "사진 정리" — 중복 파일을 완전 삭제하는 대신 앱 전용 임시 휴지통
폴더로 옮긴다("원본 보호" 원칙과 절충: 실수해도 파일이 진짜로 없어지지
않고 이 폴더에 남아있음). 옮길 때 원래 경로를 매니페스트(_MANIFEST_NAME)에
같이 남겨서, restore_from_trash()로 원래 위치에 되돌릴 수 있게 한다.

파일은 항상 TRASH_DIR 바로 아래 평평하게 저장한다 — "정리 실행" 1회에
옮겨진 파일들을 묶어보거나 왜 옮겨졌는지 알아야 할 때 쓰는 정보(group_id/
reason/kept_path)는 파일 시스템(폴더·텍스트 파일)이 아니라 매니페스트에만
기록한다. 탐색기로 이 폴더를 열면 옮겨진 사진들만 순수하게 보이고, "왜
옮겨졌는지"는 PicMedic 화면(gui/trash_screen.py)에서만 확인할 수 있다.

(예전엔 "정리 실행" 1회 = 그룹 서브폴더 1개 + _사유.txt였음 — 사용자가
"폴더 형식 대신 파일 형식으로, 사유는 앱 내부에서만 보이게" 요청해서
2026-09-06에 지금 구조로 바꿨다. 이미 옛 폴더 구조로 쌓여있던 실제 파일은
migrate_group_folders_to_flat()으로 새 구조로 옮겼다.)
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 실행 파일: __file__은 임시 압축해제 폴더를 가리키므로
    # 실제 .exe 옆에 남도록 sys.executable 기준으로 잡는다 (utils/logger.py와 동일 방식).
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent

TRASH_DIR = _BASE_DIR / "임시휴지통"
_MANIFEST_NAME = ".trash_manifest.json"
_OLD_REASON_NAME = "_사유.txt"  # migrate_group_folders_to_flat()이 예전 그룹 폴더를 읽을 때만 씀
_OLD_KEPT_MARKER = "남긴 파일: "  # 예전 _사유.txt 포맷("사유\n\n남긴 파일: 경로") 파싱용


def trash_dir() -> Path:
    return TRASH_DIR


def _manifest_path() -> Path:
    return TRASH_DIR / _MANIFEST_NAME


def _load_manifest() -> dict:
    manifest_path = _manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest: dict) -> None:
    _manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def new_group_id() -> str:
    """"같이 옮겨진 파일들"(예: 중복 그룹 하나) 묶음을 나타내는 식별자 —
    폴더를 만들지 않으므로 매니페스트 안에서만 쓰이는 문자열 태그다. 사람이
    보기 쉽게 시각을 앞에 붙이고(오래된 순 정렬용), 뒤에 짧은 uuid를 붙여
    유일함을 보장한다 — gui/trash_worker.py처럼 같은 "정리 실행" 한 번에
    여러 그룹을 빠르게 연달아 만들면 같은 초 안에 호출이 몰릴 수 있어서,
    시각만으로는(초 단위) 서로 다른 그룹이 우연히 같은 값을 받아 화면에서
    하나로 합쳐 보이는 문제가 있었다(실사용 중 발견)."""
    return f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _unique_dest(name: str) -> Path:
    """TRASH_DIR 바로 아래에서 이름이 겹치지 않는 목적지를 찾는다(원본을
    덮어쓰지 않도록 번호를 붙임)."""
    stem = Path(name).stem
    suffix = Path(name).suffix
    dest = TRASH_DIR / name
    counter = 1
    while dest.exists():
        dest = TRASH_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest


def move_to_trash(
    path: str | Path,
    *,
    group_id: str | None = None,
    reason: str | None = None,
    kept_path: str | Path | None = None,
) -> Path:
    """파일 하나를 임시 휴지통(TRASH_DIR 바로 아래, 평평하게)으로 옮기고
    최종 경로를 반환한다. group_id/reason/kept_path는 "정리 실행" 1회로
    같이 옮겨진 파일들을 나중에 화면에서 카드 하나로 묶어 보여주기 위한
    정보로, 매니페스트에만 기록된다(파일 시스템엔 안 남음). 이름이 이미
    있으면 원본을 덮어쓰지 않도록 번호를 붙인다. restore_from_trash()로
    되돌릴 수 있게 원래 경로도 같이 남긴다."""
    path = Path(path)
    original = str(path.resolve())
    TRASH_DIR.mkdir(parents=True, exist_ok=True)

    dest = _unique_dest(path.name)
    shutil.move(str(path), str(dest))

    manifest = _load_manifest()
    entry: dict = {"original": original}
    if group_id is not None:
        entry["group_id"] = group_id
    if reason is not None:
        entry["reason"] = reason
    if kept_path is not None:
        entry["kept_path"] = str(kept_path)
    manifest[dest.name] = entry
    _save_manifest(manifest)

    return dest


def entry_for(path: str | Path) -> dict | None:
    """path 하나의 매니페스트 항목을 돌려준다(original/group_id/reason/
    kept_path 중 있는 것만). 없으면 None. 이 기능이 생기기 전에 평평하게
    옮겨진 옛 항목(문자열 값만 있음)은 {"original": 그 문자열}로 정규화해서
    돌려준다."""
    manifest = _load_manifest()
    entry = manifest.get(Path(path).name)
    if entry is None:
        return None
    if isinstance(entry, str):
        return {"original": entry}
    return entry


def restore_from_trash(path: str | Path) -> Path:
    """임시 휴지통에 있는 파일 하나를 원래 있던 폴더로 되돌린다.
    원래 경로를 모르면(매니페스트에 없음) ValueError. 원래 폴더가 사라졌으면
    새로 만들고, 같은 이름 파일이 이미 있으면 번호를 붙여 덮어쓰지 않는다."""
    path = Path(path)
    manifest = _load_manifest()
    key = path.name
    entry = manifest.get(key)
    if not entry:
        raise ValueError(f"원래 위치를 알 수 없는 파일입니다: {path.name}")
    original = entry["original"] if isinstance(entry, dict) else entry

    dest = Path(original)
    dest.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    while dest.exists():
        dest = dest.parent / f"{Path(original).stem}_{counter}{Path(original).suffix}"
        counter += 1

    shutil.move(str(path), str(dest))

    del manifest[key]
    _save_manifest(manifest)

    return dest


def list_trash() -> list[Path]:
    """임시 휴지통에 있는 파일 목록(평평한 구조 — 매니페스트 자체는 제외).
    존재하지 않으면 빈 목록."""
    if not TRASH_DIR.exists():
        return []
    return sorted(
        (p for p in TRASH_DIR.iterdir() if p.is_file() and p.name != _MANIFEST_NAME),
        key=lambda p: p.name,
    )


def migrate_group_folders_to_flat() -> tuple[int, list[str]]:
    """옛 폴더 구조(TRASH_DIR/<그룹폴더>/파일들 + _사유.txt)로 남아있는 파일을
    지금 구조(TRASH_DIR 바로 아래 평평하게 + 매니페스트에 group_id/reason/
    kept_path)로 옮긴다. 옮길 옛 폴더가 없으면 아무 일도 안 하므로 여러 번
    실행해도 안전하다. 반환값: (옮긴 파일 수, 실패 메시지 목록)."""
    if not TRASH_DIR.exists():
        return 0, []

    manifest = _load_manifest()
    moved_count = 0
    failed: list[str] = []

    old_dirs = [d for d in TRASH_DIR.iterdir() if d.is_dir()]
    for group_dir in old_dirs:
        reason_file = group_dir / _OLD_REASON_NAME
        reason_text = None
        kept_path = None
        if reason_file.exists():
            try:
                content = reason_file.read_text(encoding="utf-8")
                if f"\n\n{_OLD_KEPT_MARKER}" in content:
                    reason_part, kept_part = content.split(f"\n\n{_OLD_KEPT_MARKER}", 1)
                    reason_text = reason_part.strip()
                    kept_path = kept_part.strip()
                else:
                    reason_text = content.strip()
            except OSError:
                pass

        group_id = group_dir.name  # 이미 고유한 옛 폴더명을 그대로 재사용

        for old_path in list(group_dir.iterdir()):
            if old_path.name == _OLD_REASON_NAME or not old_path.is_file():
                continue

            old_key = f"{group_dir.name}/{old_path.name}"
            old_entry = manifest.get(old_key)
            original = None
            if isinstance(old_entry, dict):
                original = old_entry.get("original")
            elif isinstance(old_entry, str):
                original = old_entry
            if original is None:
                failed.append(f"{old_path.name}: 매니페스트에서 원래 경로를 찾지 못함")
                continue

            new_dest = _unique_dest(old_path.name)
            try:
                shutil.move(str(old_path), str(new_dest))
            except OSError as exc:
                failed.append(f"{old_path.name}: {exc}")
                continue

            manifest.pop(old_key, None)
            new_entry: dict = {"original": original, "group_id": group_id}
            if reason_text:
                new_entry["reason"] = reason_text
            if kept_path:
                new_entry["kept_path"] = kept_path
            manifest[new_dest.name] = new_entry
            moved_count += 1

        try:
            if reason_file.exists():
                reason_file.unlink()
            if not list(group_dir.iterdir()):
                group_dir.rmdir()
        except OSError as exc:
            failed.append(f"{group_dir.name} 폴더 정리 실패: {exc}")

    _save_manifest(manifest)
    return moved_count, failed
