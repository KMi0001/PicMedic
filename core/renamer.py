"""
core/renamer.py

"이름 일괄변경" 실행 로직 — gui/rename_dialog.py(검사 결과 화면/홈 화면에서 연
독립된 이름변경 팝업)가 계산한 새 파일명대로, 선택된 파일을 원래 있던 폴더
그 자리에서 rename한다. core/date_organizer.py의 정리(복사/이동) 흐름과는
별개 동작 — 여기는 새 사본을 만들지 않고 기존 파일의 이름만 바꾼다.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from models.file_info import FileInfo
from utils import logger

# core/date_organizer.py::_classify_os_error, core/converter.py::_classify_os_error와
# 같은 근거(파일 잠금/저장 공간 부족 winerror) — 이 저장소는 이 정도 크기의 헬퍼는
# 모듈마다 각자 작은 사본을 둔다(새 공용 모듈을 안 만드는 게 기존 관례).
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
class RenameOutcome:
    original: FileInfo
    new_path: Optional[str] = None
    success: bool = False
    error_message: Optional[str] = None


def _unique_rename_target(directory: Path, filename: str, source: Path) -> Path:
    """directory 안에서 filename과 충돌하지 않는 경로를 만든다(뒤에 번호를 붙임
    — core/date_organizer.py::_unique_destination과 같은 충돌 회피 방식).
    계산된 자리가 source 자신과 같으면(이미 그 이름) 그대로 반환해 no-op 처리."""
    candidate = directory / filename
    if candidate == source:
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def rename_batch(
    files: list[FileInfo],
    filename_for: Callable[[FileInfo, int], str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[RenameOutcome]:
    """files를 filename_for(info, index)가 정해주는 이름으로 원래 폴더 그
    자리에서 바꾼다. 순번은 files의 순서를 그대로 따르므로, "화면에 보이는
    순서 = 매겨지는 번호 순서"가 되도록 호출부가 미리 정렬해서 넘겨야 한다."""
    total = len(files)
    outcomes: list[RenameOutcome] = []

    for index, info in enumerate(files):
        if should_cancel is not None and should_cancel():
            break
        if progress_callback:
            progress_callback(index + 1, total, info.filename)

        outcome = RenameOutcome(original=info)
        try:
            source = Path(info.path)
            new_name = filename_for(info, index)
            dest = _unique_rename_target(source.parent, new_name, source)
            if dest != source:
                source.rename(dest)
        except OSError as exc:
            outcome.error_message, abort = _classify_os_error(exc)
            outcomes.append(outcome)
            logger.log_rename(outcome)
            if abort:
                break
            continue

        outcome.new_path = str(dest)
        outcome.success = True
        outcomes.append(outcome)
        logger.log_rename(outcome)

    return outcomes
