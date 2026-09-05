"""
core/date_organizer.py

Phase 2-2 "날짜별 정리" 실행 로직 — gui/date_organize_screen.py가 미리보기로
보여준 그룹(models/scan_result.py::ScanResult.date_groups())을 실제로
"YYYY/MM"(또는 연 단위만 쓰면 "YYYY") 폴더 구조로 복사(기본)하거나 이동한다.
"날짜 정보 없음" 그룹은 별도의 NO_DATE_FOLDER_NAME 폴더로 모은다.

원칙(core/converter.py와 동일): 기본은 원본을 건드리지 않는 복사이고, 이동은
호출부가 명시적으로 선택해야만 한다.
"""

from __future__ import annotations

import errno
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from models.file_info import FileInfo

NO_DATE_LABEL = "날짜 정보 없음"
NO_DATE_FOLDER_NAME = "날짜없음"

# core/converter.py::_classify_os_error와 같은 근거 — 파일 잠금/저장 공간
# 부족은 Windows에서 이 winerror들로 온다.
_WINERROR_FILE_LOCKED = 32
_WINERROR_DISK_FULL = 112


def _classify_os_error(exc: OSError) -> tuple[str, bool]:
    """(사용자에게 보여줄 메시지, 배치 전체를 중단해야 하는지)."""
    winerror = getattr(exc, "winerror", None)
    if winerror == _WINERROR_FILE_LOCKED:
        return "다른 프로그램에서 사용 중인 파일입니다.", False
    if isinstance(exc, PermissionError):
        return "이 파일에 접근할 수 없습니다.", False
    if winerror == _WINERROR_DISK_FULL or exc.errno == errno.ENOSPC:
        return "저장 공간이 부족합니다.", True
    return str(exc), False


@dataclass
class OrganizeOutcome:
    original: FileInfo
    label: str  # 소속 그룹 라벨(예: "2024년 3월")
    output_path: Optional[str] = None
    success: bool = False
    skipped: bool = False  # 이미 정리돼 있어서 다시 복사/이동하지 않음(아래 _already_organized)
    error_message: Optional[str] = None


def _already_organized(dest: Path, source_size: int) -> bool:
    """dest 자리에 이미 같은 이름 + 같은 용량의 파일이 있으면 "이미 정리된
    파일"로 본다 — "정리하기"를 실수로 두 번 누르거나, 같은 저장 위치에
    나중에 사진을 몇 장 더 추가할 때 중복 복사를 막기 위함. 용량이 다르면
    다른 사진이 우연히 이름만 같은 경우이므로, 그때는 밑에서 번호를 붙여
    새로 복사한다(_unique_destination)."""
    try:
        return dest.is_file() and dest.stat().st_size == source_size
    except OSError:
        return False


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    """dest_dir 안에서 filename과 충돌하지 않는 경로를 만든다 — 원본 파일명은
    최대한 그대로 유지한다(utils/trash.py::move_to_trash와 같은 충돌 회피 방식)."""
    dest = dest_dir / filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest


def organize_by_date(
    groups: list[tuple[str, list[FileInfo]]],
    mode: str,  # "copy" | "move"
    output_root: str | Path,
    granularity: str = "month",  # "month" | "year" — 목적지 폴더 깊이(YYYY/MM vs YYYY)
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[OrganizeOutcome]:
    """groups를 output_root 아래 날짜 폴더로 복사/이동한다. 각 그룹의 연/월은
    파일명 문자열을 다시 파싱하는 대신, 그 그룹에 속한 파일들이 이미 공유하는
    FileInfo.captured_at에서 그대로 가져온다(그룹핑 기준과 실행 기준을 하나로
    유지 — ScanResult.date_groups() 참고). "날짜 정보 없음" 그룹은
    NO_DATE_FOLDER_NAME 폴더 하나로 모은다."""
    output_root = Path(output_root)
    total = sum(len(files) for _, files in groups)

    outcomes: list[OrganizeOutcome] = []
    processed = 0

    for label, files in groups:
        if not files:
            continue

        if label == NO_DATE_LABEL:
            dest_dir = output_root / NO_DATE_FOLDER_NAME
        else:
            captured = files[0].captured_at
            if granularity == "year":
                dest_dir = output_root / f"{captured.year:04d}"
            else:
                dest_dir = output_root / f"{captured.year:04d}" / f"{captured.month:02d}"

        for info in files:
            processed += 1
            if should_cancel is not None and should_cancel():
                return outcomes
            if progress_callback:
                progress_callback(processed, total, info.filename)

            outcome = OrganizeOutcome(original=info, label=label)
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)

                direct_dest = dest_dir / info.filename
                if _already_organized(direct_dest, info.file_size):
                    # 이미 같은 이름+용량의 파일이 그 자리에 있음 — 다시 복사/
                    # 이동하지 않고 건너뛴다. 이동 모드여도 원본은 그대로 둔다
                    # (이미 정리된 것으로 보이는 상황에서 원본을 지우는 건
                    # 너무 위험한 판단이라, 안전한 쪽인 "손대지 않음"을 택함).
                    outcome.output_path = str(direct_dest)
                    outcome.success = True
                    outcome.skipped = True
                    outcomes.append(outcome)
                    continue

                dest = _unique_destination(dest_dir, info.filename)
                if mode == "move":
                    shutil.move(info.path, str(dest))
                else:
                    shutil.copy2(info.path, dest)
            except OSError as exc:
                outcome.error_message, abort = _classify_os_error(exc)
                outcomes.append(outcome)
                if abort:
                    return outcomes
                continue

            outcome.output_path = str(dest)
            outcome.success = True
            outcomes.append(outcome)

    return outcomes
