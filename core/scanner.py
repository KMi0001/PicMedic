"""
core/scanner.py

PRD 6장 "폴더/파일 선택", 12장 "일괄 처리" 구현.
폴더(또는 단일 파일)를 순회하며 analyzer.analyze_file()로 각 파일을 진단하고
ScanResult로 집계한다. GUI에서 진행률을 보여줄 수 있도록 콜백을 지원한다.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.analyzer import analyze_file
from core.detector import MVP_SUPPORTED_EXTENSIONS, FUTURE_EXTENSIONS
from models.file_info import FileInfo
from models.scan_result import ScanResult
from utils import logger
from utils.trash import TRASH_FOLDER_NAME

# PRD_MVP우선순위.md 갭 #8 조사로 확인됨: HEIC/HEIF는 HEVC 기반 디코딩이라
# JPEG보다 10배 이상 느리다(실측 0.3~0.7초/장 vs JPEG 0.03초대). 이 형식이
# 섞인 폴더는 검사가 눈에 띄게 오래 걸릴 수 있어 진행 화면에 안내를 띄운다.
HEAVY_DECODE_FORMATS = {"HEIC", "HEIF"}

# 스캔 대상으로 삼을 확장자: MVP 지원 + 향후 지원 예정(지원 불가로 표시하기 위해 포함)
SCANNABLE_EXTENSIONS = MVP_SUPPORTED_EXTENSIONS | FUTURE_EXTENSIONS

ProgressCallback = Callable[[int, int, str], None]  # (current, total, filename)


def _is_candidate(path: Path, extensions: frozenset[str]) -> bool:
    # macOS가 만드는 리소스 포크(AppleDouble) 파일: 원본과 같은 확장자를 쓰지만
    # 실제로는 이미지가 아닌 메타데이터라 손상 파일로 오탐된다.
    if path.name.startswith("._"):
        return False
    # 확장자가 전혀 이미지가 아닌 것으로 보이는 파일(.txt, .exe 등)은 건너뛴다.
    # 단, PRD 23.7 "잘못된 확장자" 케이스(확장자는 이미지인데 내용이 다름)는
    # 확장자 기준으로는 잡히므로 문제 없다.
    return path.suffix.lower() in extensions


def iter_candidate_files(
    root: Path,
    recursive: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
    extensions: Optional[frozenset[str]] = None,
) -> Iterable[Path]:
    """검사 대상이 될 수 있는 파일들을 나열한다 (확장자 기준 1차 필터링).

    macOS에서는 iCloud Drive/사진 라이브러리 등에 자기 자신(또는 상위 폴더)을
    가리키는 심볼릭 링크가 흔해서, 단순히 글롭으로 재귀 순회하면 무한 루프에
    빠질 수 있다. 실제 경로(resolve) 기준으로 이미 방문한 디렉터리는 다시
    내려가지 않도록 막고, 순회 도중에도 should_cancel을 체크해 즉시 중단할
    수 있게 한다 (예전엔 이 단계가 끝나야만 취소 체크 루프에 도달했음).

    extensions를 안 주면 기본(SCANNABLE_EXTENSIONS, 이미지)으로 찾는다 — 이미지가
    아닌 다른 확장자(예: 라이브 포토용 .mov)를 찾을 때도 이 함수의 AppleDouble
    필터링/심볼릭 링크 순환 차단을 그대로 쓰려면 extensions만 바꿔서 재사용한다.
    """
    exts = extensions if extensions is not None else SCANNABLE_EXTENSIONS
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
            if _is_candidate(path, exts):
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
        # (참고: Path.is_symlink()로 먼저 걸러서 resolve() 호출을 줄여보려 했으나,
        # 윈도우의 디렉터리 정션(mklink /J — iCloud/OneDrive가 흔히 만드는 바로 그
        # 형태)은 is_symlink()가 False를 반환해 감지를 놓친다. 그래서 모든 하위
        # 폴더에 대해 resolve()를 그대로 수행한다.)
        keep = []
        for name in dirnames:
            # 임시휴지통(utils/trash.py::TRASH_FOLDER_NAME)은 옮기려는 파일이
            # 있던 폴더 바로 밑에 생기므로, 그 부모 폴더를 재귀 검사하면 이미
            # 정리해서 치운 파일들까지 다시 검사 대상에 들어온다 — 정리 실행
            # 직후 "다시 검사"를 누르면 방금 치운 중복 사진이 또 잡히는 식.
            # (2026-09-17, 사용자 요청)
            if name == TRASH_FOLDER_NAME:
                continue
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
            if _is_candidate(path, exts):
                yield path


def _scan_files(
    files: list[Path],
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_heavy_format: Optional[Callable[[], None]] = None,
) -> ScanResult:
    total = len(files)
    result = ScanResult()
    heavy_format_seen = False

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

        # HEIC/HEIF가 섞여 있으면 검사가 눈에 띄게 오래 걸릴 수 있어(위 HEAVY_DECODE_FORMATS
        # 주석 참고), 진행 화면이 처음 발견한 시점에 딱 한 번 안내를 띄울 수 있게 알려준다.
        if not heavy_format_seen and info.detected_format in HEAVY_DECODE_FORMATS:
            heavy_format_seen = True
            if on_heavy_format:
                on_heavy_format()

        result.add(info)

        if progress_callback:
            progress_callback(idx, total, path.name)

    return result


def scan_folder(
    root: str | Path,
    recursive: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_heavy_format: Optional[Callable[[], None]] = None,
) -> tuple[ScanResult, list[str]]:
    """폴더(or 단일 파일) 하나를 스캔한다. (ScanResult, 아직 검사 못한 파일 경로 목록)을 반환한다."""
    return scan_paths(
        [root],
        recursive=recursive,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
        on_heavy_format=on_heavy_format,
    )


def _gather_candidate_files(
    roots: Iterable[str | Path],
    recursive: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[Path]:
    """여러 경로에서 검사 대상 파일 목록만 모은다(같은 파일이 여러 경로로
    중복 포함되면 한 번만). scan_paths()와 list_image_files() 둘 다 이걸로
    파일을 모으고, 그다음 뭘 할지(analyze_file 전체 진단 vs 목록만)만 갈린다."""
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
    return files


def scan_paths(
    roots: Iterable[str | Path],
    recursive: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_heavy_format: Optional[Callable[[], None]] = None,
) -> tuple[ScanResult, list[str]]:
    """
    여러 파일/폴더 경로를 한 번에 스캔하여 ScanResult 하나로 합친다.
    (PRD FR-001 '다중 선택' — 파일 선택 다이얼로그에서 여러 파일을 고르거나
    드래그 앤 드롭으로 여러 항목을 끌어놓는 경우)

    - progress_callback(current, total, filename): 매 파일 처리 후 호출
    - should_cancel(): True를 반환하면 남은 파일 처리를 중단 (PRD Screen 02 '취소')
    - on_heavy_format(): HEIC/HEIF처럼 디코딩이 무거운 형식을 스캔 중 처음 발견하면
      한 번 호출된다 (진행 화면에서 "오래 걸릴 수 있음" 안내를 띄우는 용도).
    - 같은 파일이 여러 경로(예: 폴더 스캔과 개별 파일 선택)로 중복 포함되면 한 번만 검사한다.

    반환값: (ScanResult, remaining_paths)
    - remaining_paths: 취소로 인해 아직 검사하지 못한 파일 경로 목록 (이어서 검사할 때 사용).
      끝까지 검사했다면 빈 리스트.
    """
    roots = list(roots)
    files = _gather_candidate_files(roots, recursive=recursive, should_cancel=should_cancel)

    result = _scan_files(
        files, progress_callback=progress_callback, should_cancel=should_cancel, on_heavy_format=on_heavy_format
    )
    logger.log_scan(", ".join(str(r) for r in roots), result)

    remaining_paths = [str(p) for p in files[result.total:]]
    return result, remaining_paths


@dataclass
class RestoreStats:
    """scan_paths_incremental이 저장된 작업과 지금 폴더를 비교한 결과 요약."""

    reused: int = 0  # 그대로라서 재사용한 사진
    added: int = 0  # 새로 생겨 분석한 사진
    changed: int = 0  # 내용(크기/수정시각)이 바뀌어 다시 분석한 사진
    removed: int = 0  # 저장본에는 있었지만 지금은 없는 사진
    moved: dict[str, str] = field(default_factory=dict)  # 옛 경로 -> 새 경로 (다른 폴더로 옮겨진 것으로 판단한 사진)
    changed_paths: set[str] = field(default_factory=set)  # changed에 해당하는 경로(카테고리 재분류 대상)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed or self.moved)


def scan_paths_incremental(
    roots: Iterable[str | Path],
    known: list[FileInfo],
    recursive: bool = True,
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_heavy_format: Optional[Callable[[], None]] = None,
) -> tuple[ScanResult, list[str], RestoreStats]:
    """scan_paths와 같지만, 이전에 저장한 검사 결과(known)와 비교해서 무거운
    분석(해시+디코딩)을 변경된 사진에만 한다(2026-09-20 — core/session_store.py).

    사진마다 판단:
    - 경로가 같고 크기·수정시각도 같으면 -> 그대로 재사용
    - 경로는 같은데 크기나 수정시각이 다르면 -> 바뀐 파일, 다시 분석
    - 저장본에 없는 경로 -> 새 파일. 단, 저장본에는 있는데 지금은 없는 파일과
      (파일명, 크기, 수정시각)이 같으면 사용자가 다른 폴더로 옮긴 같은 사진으로
      보고 재사용한다(경로만 새것으로). 파일 내용 해시까지 비교하지 않는 건
      3만 장을 다시 읽어야 해서 재사용의 의미가 없어지기 때문 — 우연히 이름·
      크기·수정시각이 모두 같은 다른 사진일 가능성은 사실상 무시한다.
    - 저장본에만 있는 경로(짝이 안 맞는 것) -> 삭제된 것으로 보고 뺀다

    반환 remaining_paths는 scan_paths와 같은 의미(취소로 아직 분석 못 한 파일들) —
    재사용한 사진은 이미 결과에 들어 있으니 분석 대상 중에서만 나온다."""
    roots = list(roots)
    files = _gather_candidate_files(roots, recursive=recursive, should_cancel=should_cancel)

    known_by_path = {os.path.normcase(info.path): info for info in known}
    stats = RestoreStats()
    reused: list[FileInfo] = []
    to_analyze: list[Path] = []
    new_paths: list[Path] = []  # 저장본에 없던 경로 — 아래에서 "옮겨진 사진"인지 한 번 더 본다
    seen: set[str] = set()

    for path in files:
        key = os.path.normcase(str(path))
        seen.add(key)
        old = known_by_path.get(key)
        if old is None:
            new_paths.append(path)
            continue
        try:
            st = path.stat()
        except OSError:
            to_analyze.append(path)
            stats.changed += 1
            stats.changed_paths.add(old.path)
            continue
        if old.mtime_ns and old.mtime_ns == st.st_mtime_ns and old.file_size == st.st_size:
            reused.append(old)
        else:
            to_analyze.append(path)
            stats.changed += 1
            stats.changed_paths.add(old.path)

    missing = [info for key, info in known_by_path.items() if key not in seen]
    missing_by_signature: dict[tuple[str, int, int], list[FileInfo]] = {}
    for info in missing:
        if info.mtime_ns:
            missing_by_signature.setdefault((info.filename, info.file_size, info.mtime_ns), []).append(info)

    for path in new_paths:
        try:
            st = path.stat()
            candidates = missing_by_signature.get((path.name, st.st_size, st.st_mtime_ns))
        except OSError:
            candidates = None
        if candidates:
            old = candidates.pop()
            moved = dataclasses.replace(old, path=str(path))
            reused.append(moved)
            stats.moved[old.path] = moved.path
        else:
            to_analyze.append(path)
            stats.added += 1

    stats.reused = len(reused) - len(stats.moved)
    stats.removed = len(missing) - len(stats.moved)

    result = ScanResult()
    for info in reused:
        result.add(info)
    analyzed = _scan_files(
        to_analyze, progress_callback=progress_callback, should_cancel=should_cancel, on_heavy_format=on_heavy_format
    )
    result = result.merge(analyzed)
    logger.log_scan(", ".join(str(r) for r in roots), result)

    remaining_paths = [str(p) for p in to_analyze[analyzed.total:]]
    return result, remaining_paths, stats


def list_image_files(
    roots: Iterable[str | Path],
    recursive: bool = True,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ScanResult:
    """core/analyzer.py의 무거운 분석(파일 전체 SHA-256 해시 + 이미지 디코딩
    + 퍼셉추얼 해시/EXIF)을 생략하고 파일 목록만 가볍게 모은다.

    2026-09-10, 사용자 요청 — 사진 3만 장 규모에서 "정리 > 동물친구들"이
    "검사"와 똑같이 느렸던 문제. core/category_finder.py(CLIP)는 원본 이미지를
    직접 읽으므로 손상 검사·해시가 전혀 필요 없어서, 이 함수로 만든
    가벼운 ScanResult를 바로 넘기면 된다 — 대신 FileInfo의 status/width/
    height/EXIF 등은 채워지지 않는다(gui/organize_hub_screen.py의 중복·
    유사·날짜별·도시별처럼 그 값이 필요한 기능에는 이 결과를 쓰면 안 됨).
    """
    files = _gather_candidate_files(roots, recursive=recursive, should_cancel=should_cancel)
    result = ScanResult()
    for path in files:
        if should_cancel and should_cancel():
            break
        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = 0
        result.add(
            FileInfo(
                path=str(path),
                filename=path.name,
                extension=path.suffix.lower(),
                file_size=file_size,
                readable=True,
            )
        )
    return result
