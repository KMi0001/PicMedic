"""
utils/trash.py

Phase 2 "사진 정리" — 중복 파일을 완전 삭제하는 대신 앱 전용 임시 휴지통
폴더로 옮긴다("원본 보호" 원칙과 절충: 실수해도 파일이 진짜로 없어지지
않고 이 폴더에 남아있음). 옮길 때 원래 경로를 매니페스트(_MANIFEST_NAME)에
같이 남겨서, restore_from_trash()로 원래 위치에 되돌릴 수 있게 한다.

정리를 한 번 실행("정리 실행" 버튼 클릭 1회)하면, 그때 옮겨진 중복 그룹들은
각자 그룹 서브폴더(create_trash_group())에 모인다 — 나중에 "왜 옮겨졌는지"
(_REASON_NAME) 맥락 없이 파일만 덩그러니 남는 문제를 막기 위함. group_dir을
지정하지 않고 move_to_trash()를 호출하면 예전처럼 TRASH_DIR 바로 아래 평평하게
옮겨진다(그룹 개념이 필요 없는 호출부와의 호환용).
"""

from __future__ import annotations

import json
import shutil
import sys
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
_REASON_NAME = "_사유.txt"


def trash_dir() -> Path:
    return TRASH_DIR


def _manifest_path() -> Path:
    return TRASH_DIR / _MANIFEST_NAME


def _load_manifest() -> dict[str, str | dict]:
    manifest_path = _manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest: dict[str, str | dict]) -> None:
    _manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def new_session_timestamp() -> str:
    """"정리 실행" 한 번(버튼 클릭 1회)에 옮겨지는 모든 그룹이 공유하는
    시각 문자열 — 그룹 폴더 이름의 접두어로 쓴다."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def create_trash_group(session_timestamp: str, group_index: int, keep_path: str | Path, reason: str) -> Path:
    """중복 그룹 하나를 위한 서브폴더를 만들고, 왜 옮겨졌는지·무엇을 남겼는지를
    _사유.txt에 적어둔다. move_to_trash(path, group_dir=...)에 이 폴더를
    넘기면 그 그룹의 파일들이 여기로 모인다."""
    group_dir = TRASH_DIR / f"{session_timestamp}_그룹{group_index:04d}"
    counter = 1
    while group_dir.exists():
        group_dir = TRASH_DIR / f"{session_timestamp}_그룹{group_index:04d}_{counter}"
        counter += 1
    group_dir.mkdir(parents=True, exist_ok=True)
    (group_dir / _REASON_NAME).write_text(f"{reason}\n\n남긴 파일: {keep_path}", encoding="utf-8")
    return group_dir


def group_reason(path: str | Path) -> str | None:
    """휴지통 안의 파일 하나가 속한 그룹의 _사유.txt 내용을 읽어온다.
    그룹 폴더가 아니거나(평평하게 옮겨진 옛 파일) 사유 파일이 없으면 None."""
    reason_path = Path(path).parent / _REASON_NAME
    if not reason_path.exists():
        return None
    try:
        return reason_path.read_text(encoding="utf-8")
    except OSError:
        return None


_KEPT_MARKER = "남긴 파일: "


def group_reason_summary(path: str | Path) -> str | None:
    """group_reason()에서 사유 설명 부분만 뽑는다(남긴 파일 경로 줄 제외) —
    검수 화면 카드 제목처럼 사람이 짧게 읽을 자리에 쓴다."""
    reason = group_reason(path)
    if reason is None:
        return None
    return reason.split(f"\n\n{_KEPT_MARKER}", 1)[0].strip()


def group_kept_path(path: str | Path) -> str | None:
    """group_reason()에 같이 기록된 "남긴 파일"의 원래 경로를 뽑는다
    (create_trash_group()이 쓰는 형식과 짝을 이룸). 그룹 폴더가 아니거나
    사유 파일이 없으면 None."""
    reason = group_reason(path)
    if reason is None:
        return None
    idx = reason.rfind(_KEPT_MARKER)
    if idx == -1:
        return None
    return reason[idx + len(_KEPT_MARKER):].strip()


def move_to_trash(path: str | Path, group_dir: Path | None = None) -> Path:
    """파일 하나를 임시 휴지통(또는 group_dir로 지정한 그룹 서브폴더)으로
    옮기고 최종 경로를 반환한다. 이름이 이미 있으면 원본을 덮어쓰지 않도록
    번호를 붙인다. 나중에 restore_from_trash()로 되돌릴 수 있게 원래 경로를
    매니페스트에 남긴다."""
    path = Path(path)
    original = str(path.resolve())
    dest_base = group_dir if group_dir is not None else TRASH_DIR
    dest_base.mkdir(parents=True, exist_ok=True)

    dest = dest_base / path.name
    counter = 1
    while dest.exists():
        dest = dest_base / f"{path.stem}_{counter}{path.suffix}"
        counter += 1

    shutil.move(str(path), str(dest))

    manifest = _load_manifest()
    key = dest.relative_to(TRASH_DIR).as_posix()
    if group_dir is not None:
        manifest[key] = {"original": original, "group": group_dir.name}
    else:
        manifest[key] = original
    _save_manifest(manifest)

    return dest


def restore_from_trash(path: str | Path) -> Path:
    """임시 휴지통에 있는 파일 하나를 원래 있던 폴더로 되돌린다.
    원래 경로를 모르면(매니페스트에 없음 — 이 기능이 생기기 전에 옮겨졌거나
    사용자가 직접 넣은 파일) ValueError. 원래 폴더가 사라졌으면 새로 만들고,
    같은 이름 파일이 이미 있으면 번호를 붙여 덮어쓰지 않는다. 그룹 폴더에서
    마지막 파일을 복원하면(사유 파일만 남으면) 빈 그룹 폴더도 같이 정리한다."""
    path = Path(path)
    manifest = _load_manifest()
    key = path.relative_to(TRASH_DIR).as_posix()
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

    group_dir = path.parent
    if group_dir != TRASH_DIR and group_dir.exists():
        remaining = list(group_dir.iterdir())
        if not remaining or remaining == [group_dir / _REASON_NAME]:
            reason_file = group_dir / _REASON_NAME
            if reason_file.exists():
                reason_file.unlink()
            group_dir.rmdir()

    return dest


def list_trash() -> list[Path]:
    """임시 휴지통에 있는 파일 목록(그룹 서브폴더 안까지 재귀적으로, 존재하지
    않으면 빈 목록). 매니페스트/사유 파일 자체는 목록에 포함하지 않는다."""
    if not TRASH_DIR.exists():
        return []
    return sorted(
        (
            p
            for p in TRASH_DIR.rglob("*")
            if p.is_file() and p.name not in (_MANIFEST_NAME, _REASON_NAME)
        ),
        key=lambda p: p.relative_to(TRASH_DIR).as_posix(),
    )
