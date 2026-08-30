"""
core/scanner.py

PRD 6장 "폴더/파일 선택", 12장 "일괄 처리" 구현.
폴더(또는 단일 파일)를 순회하며 analyzer.analyze_file()로 각 파일을 진단하고
ScanResult로 집계한다. GUI에서 진행률을 보여줄 수 있도록 콜백을 지원한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.analyzer import analyze_file
from core.detector import MVP_SUPPORTED_EXTENSIONS, FUTURE_EXTENSIONS
from models.scan_result import ScanResult
from utils import logger

# 스캔 대상으로 삼을 확장자: MVP 지원 + 향후 지원 예정(지원 불가로 표시하기 위해 포함)
SCANNABLE_EXTENSIONS = MVP_SUPPORTED_EXTENSIONS | FUTURE_EXTENSIONS

ProgressCallback = Callable[[int, int, str], None]  # (current, total, filename)


def _is_candidate(path: Path) -> bool:
    # macOS가 만드는 리소스 포크(AppleDouble) 파일: 원본과 같은 확장자를 쓰지만
    # 실제로는 이미지가 아닌 메타데이터라 손상 파일로 오탐된다.
    if path.name.startswith("._"):
        return False
    # 확장자가 전혀 이미지가 아닌 것으로 보이는 파일(.txt, .exe 등)은 건너뛴다.
    # 단, PRD 23.7 "잘못된 확장자" 케이스(확장자는 이미지인데 내용이 다름)는
    # 확장자 기준으로는 잡히므로 문제 없다.
    return path.suffix.lower() in SCANNABLE_EXTENSIONS


def iter_candidate_files(
    root: Path,
    recursive: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Iterable[Path]:
    """검사 대상이 될 수 있는 파일들을 나열한다 (확장자 기준 1차 필터링).

    macOS에서는 iCloud Drive/사진 라이브러리 등에 자기 자신(또는 상위 폴더)을
    가리키는 심볼릭 링크가 흔해서, 단순히 글롭으로 재귀 순회하면 무한 루프에
    빠질 수 있다. 실제 경로(resolve) 기준으로 이미 방문한 디렉터리는 다시
    내려가지 않도록 막고, 순회 도중에도 should_cancel을 체크해 즉시 중단할
    수 있게 한다 (예전엔 이 단계가 끝나야만 취소 체크 루프에 도달했음).
    """
    if root.is_file():
        yield root
        return

    if not recursive:
        try:
            entries = list(os.scandir(root))
        except OSError:
            return
        for entry in entries:
            if should_cancel and should_cancel():
                return
            path = Path(entry.path)
            if not path.is_file():
                continue
            if _is_candidate(path):
                yield path
        return

    visited_dirs: set[Path] = set()
    try:
        visited_dirs.add(root.resolve())
    except OSError:
        pass

    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        if should_cancel and should_cancel():
            return

        # 순환 심볼릭 링크 차단: 실제 경로가 이미 방문한 디렉터리면 더 내려가지 않는다.
        keep = []
        for name in dirnames:
            try:
                real = (Path(dirpath) / name).resolve()
            except OSError:
                continue
            if real in visited_dirs:
                continue
            visited_dirs.add(real)
            keep.append(name)
        dirnames[:] = keep

        for name in filenames:
            if should_cancel and should_cancel():
                return
            path = Path(dirpath) / name
            if not path.is_file():
                continue
            if _is_candidate(path):
                yield path


def _scan_files(
    files: list[Path],
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ScanResult:
    total = len(files)
    result = ScanResult()

    for idx, path in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break

        try:
            info = analyze_file(path)
        except Exception as exc:  # PRD 23.4: 개별 파일 오류가 전체 작업을 막아선 안 된다
            from models.file_info import FileInfo, FileStatus

            info = FileInfo(
                path=str(path),
                filename=path.name,
                extension=path.suffix.lower(),
                status=FileStatus.UNKNOWN,
                error_message=f"분석 중 예외 발생: {exc}",
            )

        result.add(info)

        if progress_callback:
            progress_callback(idx, total, path.name)

    return result


def scan_folder(
    root: str | Path,
    recursive: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[ScanResult, list[str]]:
    """폴더(or 단일 파일) 하나를 스캔한다. (ScanResult, 아직 검사 못한 파일 경로 목록)을 반환한다."""
    return scan_paths(
        [root], recursive=recursive, progress_callback=progress_callback, should_cancel=should_cancel
    )


def scan_paths(
    roots: Iterable[str | Path],
    recursive: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[ScanResult, list[str]]:
    """
    여러 파일/폴더 경로를 한 번에 스캔하여 ScanResult 하나로 합친다.
    (PRD FR-001 '다중 선택' — 파일 선택 다이얼로그에서 여러 파일을 고르거나
    드래그 앤 드롭으로 여러 항목을 끌어놓는 경우)

    - progress_callback(current, total, filename): 매 파일 처리 후 호출
    - should_cancel(): True를 반환하면 남은 파일 처리를 중단 (PRD Screen 02 '취소')
    - 같은 파일이 여러 경로(예: 폴더 스캔과 개별 파일 선택)로 중복 포함되면 한 번만 검사한다.

    반환값: (ScanResult, remaining_paths)
    - remaining_paths: 취소로 인해 아직 검사하지 못한 파일 경로 목록 (이어서 검사할 때 사용).
      끝까지 검사했다면 빈 리스트.
    """
    roots = list(roots)
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if should_cancel and should_cancel():
            break
        for path in iter_candidate_files(Path(root), recursive=recursive, should_cancel=should_cancel):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)

    result = _scan_files(files, progress_callback=progress_callback, should_cancel=should_cancel)
    logger.log_scan(", ".join(str(r) for r in roots), result)

    remaining_paths = [str(p) for p in files[result.total:]]
    return result, remaining_paths
