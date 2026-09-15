"""
core/live_photo_finder.py

"라이브 포토 찾기/정리" — HEIC(또는 아직 EXIF가 남아있는 JPG)와 그 짝 MOV가
같은 애플 Content Identifier(UUID)를 공유한다는 점을 이용해, 사진과 라이브
포토 동영상을 서로 짝지어 찾는다.

exiftool 같은 외부 프로그램 없이 pillow-heif/Pillow가 이미 주는 raw EXIF
바이트에서 UUID 형태 문자열을 정규식으로 뽑고, 같은 UUID가 MOV 파일 원본
바이트 안에도 있는지 대조하는 방식이다(애플 MakerNote의 정확한 바이너리
구조를 직접 파싱하는 대신 이 방식을 씀 — 태그가 여러 개 섞여 있어도 사진과
동영상 양쪽에 공통으로 나타나는 UUID만 실제 연결로 본다). 2026-09-15
실사용자 사진 4만 3천 장 규모 스캔(scratchpad 프로토타입)에서 검증됨.
"""

from __future__ import annotations

import errno
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import pillow_heif
from PIL import Image

from core.scanner import iter_candidate_files
from utils.file_utils import unique_recovered_path

IMAGE_EXTENSIONS = frozenset({".heic", ".heif", ".jpg", ".jpeg"})
MOV_EXTENSIONS = frozenset({".mov"})

_UUID_RE = re.compile(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")

# MOV 파일 하나당 읽는 바이트 상한 — 일반 동영상이 섞여 있어도(라이브 포토
# 클립은 보통 수 MB) 스캔이 한없이 느려지지 않게 방지.
_MOV_READ_CAP = 60 * 1024 * 1024

ProgressCallback = Callable[[int, int, str], None]

# core/converter.py::_classify_os_error와 같은 근거.
_WINERROR_FILE_LOCKED = 32
_WINERROR_DISK_FULL = 112


@dataclass(frozen=True)
class LivePhotoMatch:
    image_path: Path
    mov_path: Path


def _classify_os_error(exc: OSError) -> tuple[str, bool]:
    winerror = getattr(exc, "winerror", None)
    if winerror == _WINERROR_FILE_LOCKED:
        return "다른 프로그램에서 사용 중인 파일입니다.", False
    if isinstance(exc, PermissionError):
        return "이 파일에 접근할 수 없습니다.", False
    if winerror == _WINERROR_DISK_FULL or exc.errno == errno.ENOSPC:
        return "저장 공간이 부족합니다.", True
    return str(exc), False


def _gather(paths, extensions: frozenset[str], should_cancel) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        for path in iter_candidate_files(Path(raw), recursive=True, should_cancel=should_cancel, extensions=extensions):
            found.append(path)
            if should_cancel and should_cancel():
                return found
    return found


def _mov_uuid_map(mov_paths: list[Path], progress_callback, should_cancel, done_so_far: int, total: int) -> dict[str, list[Path]]:
    uuid_to_movs: dict[str, list[Path]] = {}
    for path in mov_paths:
        if should_cancel and should_cancel():
            break
        done_so_far += 1
        if progress_callback:
            progress_callback(done_so_far, total, path.name)
        try:
            data = path.read_bytes()[:_MOV_READ_CAP]
        except OSError:
            continue
        # set()로 중복 제거: 같은 UUID가 한 MOV의 메타데이터 안에 여러 번(예:
        # QuickTime의 서로 다른 메타데이터 위치) 나오면 setdefault().append()가
        # 같은 파일을 그 UUID 목록에 여러 번 넣어서, find_live_photo_matches의
        # "이 UUID가 MOV 정확히 1개에만 쓰였는지" 판정이 그 파일 하나뿐인데도
        # 거짓으로 실패했다(2026-09-15, 실사용자 데이터로 전체 매칭이 0개까지
        # 떨어지는 회귀로 발견).
        for m in set(_UUID_RE.findall(data)):
            uuid_to_movs.setdefault(m.decode().upper(), []).append(path)
    return uuid_to_movs


def _image_uuids(path: Path, is_heic: bool) -> Optional[set[str]]:
    """이미지 exif에서 UUID 후보를 뽑는다. 파일을 못 열면(손상 등) None."""
    try:
        if is_heic:
            heif = pillow_heif.open_heif(str(path), convert_hdr_to_8bit=False)
            exif = heif.info.get("exif")
        else:
            with Image.open(path) as img:
                exif = img.info.get("exif")
    except Exception:
        return None
    if not exif:
        return set()
    return set(m.decode().upper() for m in _UUID_RE.findall(exif))


def _dedupe_identical_movs(candidate_movs: set[Path]) -> set[Path]:
    """같은 UUID를 공유하는 MOV가 여러 개면(예: "동영상으로 내보내기"로 만든
    복사본이 스캔 범위 안에 같이 들어온 경우), 내용이 사실상 같은 파일(크기가
    같음)들은 "같은 동영상의 복사본"으로 보고 하나만 남긴다 — 진짜로 서로
    다른 두 동영상이 우연히 같은 UUID를 공유하는 경우(크기까지 같을 확률은
    사실상 0에 가까움)와 구분하기 위한 근거로 파일 크기를 쓴다.
    (2026-09-16, 사용자 리포트 — "내보내기" 결과를 원본과 같은 폴더 아래에
    둔 채로 다시 스캔하니 전부 매칭 안 됨.)"""
    if len(candidate_movs) <= 1:
        return candidate_movs
    by_size: dict[int, Path] = {}
    for p in candidate_movs:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        by_size.setdefault(size, p)
    return set(by_size.values())


def find_live_photo_matches(
    paths: list[str | Path],
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[LivePhotoMatch]:
    """paths(파일/폴더 혼합 가능) 아래를 재귀적으로 훑어, 사진<->MOV가 같은
    Content Identifier(UUID)를 공유하는 "확인된" 짝만 돌려준다. 식별자만 있고
    짝 MOV를 못 찾은 사진은(아직 라이브 포토였을 가능성은 있지만 지금 이
    범위 안에서는 확인 불가) 이 함수의 반환값에 포함하지 않는다.

    사진 exif 하나에 UUID가 2~3개씩 섞여 있는 경우가 흔해서(진짜 Content
    Identifier 말고 DocumentID 등 애플이 같이 심어두는 다른 UUID들), 그
    UUID들이 가리키는 MOV가 서로 다르면(사진 한 장이 서로 다른 MOV 여러
    개와 동시에 매칭되면) 어느 쪽이 진짜인지 알 수 없는 것으로 보고 건너뛴다
    — 예전엔 이 경우 다 매칭시켜서 "정리/내보내기"에서 같은 사진이 여러 벌
    복사되는 문제가 있었다(2026-09-15, 사용자 리포트 — 파일이 4개씩 똑같이
    생김).

    반대로 "같은 사진이 여러 폴더에 중복 백업돼 있어서 같은 UUID를 가진
    사진이 여러 장"인 경우는 흔하고 정상이라(예: 같은 사진이 날짜별 정리
    폴더·클라우드 백업 폴더에도 복사돼 있는 경우) 문제 삼지 않는다 — 대신
    MOV 하나는 결과에 한 번만 쓰이게 해서(used_movs), 중복 사진들이 같은
    동영상을 여러 번 내보내지 않게만 막는다."""
    mov_paths = _gather(paths, MOV_EXTENSIONS, should_cancel)
    image_candidates = [(p, p.suffix.lower() in (".heic", ".heif")) for p in _gather(paths, IMAGE_EXTENSIONS, should_cancel)]

    total = len(mov_paths) + len(image_candidates)
    uuid_to_movs = _mov_uuid_map(mov_paths, progress_callback, should_cancel, 0, total)

    matches: list[LivePhotoMatch] = []
    used_movs: set[Path] = set()
    done = len(mov_paths)
    for path, is_heic in image_candidates:
        if should_cancel and should_cancel():
            break
        done += 1
        if progress_callback:
            progress_callback(done, total, path.name)
        uuids = _image_uuids(path, is_heic)
        if not uuids:
            continue
        candidate_movs: set[Path] = set()
        for u in uuids:
            candidate_movs.update(uuid_to_movs.get(u, ()))
        candidate_movs = _dedupe_identical_movs(candidate_movs)
        if len(candidate_movs) != 1:
            continue
        mov_path = next(iter(candidate_movs))
        if mov_path in used_movs:
            continue
        used_movs.add(mov_path)
        matches.append(LivePhotoMatch(image_path=path, mov_path=mov_path))
    return matches


@dataclass
class LivePhotoOutcome:
    match: LivePhotoMatch
    output_image_path: Optional[str] = None
    output_mov_path: Optional[str] = None
    success: bool = False
    error_message: Optional[str] = None


def organize_live_photo_pairs(
    matches: list[LivePhotoMatch],
    output_dir: str | Path,
    mode: str = "copy",  # "copy" | "move" — core/date_organizer.py와 같은 기본값(copy, 원본 보호)
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[LivePhotoOutcome]:
    """확인된 라이브 포토 쌍(사진+MOV)을 output_dir 하나로 모은다."""
    output_dir = Path(output_dir)
    total = len(matches)
    outcomes: list[LivePhotoOutcome] = []

    for idx, match in enumerate(matches, start=1):
        if should_cancel and should_cancel():
            break
        if progress_callback:
            progress_callback(idx, total, match.image_path.name)

        outcome = LivePhotoOutcome(match=match)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            image_dest = _unique_destination(output_dir, match.image_path.name)
            mov_dest = _unique_destination(output_dir, match.mov_path.name)
            if mode == "move":
                shutil.move(str(match.image_path), str(image_dest))
                shutil.move(str(match.mov_path), str(mov_dest))
            else:
                shutil.copy2(match.image_path, image_dest)
                shutil.copy2(match.mov_path, mov_dest)
        except OSError as exc:
            outcome.error_message, abort = _classify_os_error(exc)
            outcomes.append(outcome)
            if abort:
                break
            continue

        outcome.output_image_path = str(image_dest)
        outcome.output_mov_path = str(mov_dest)
        outcome.success = True
        outcomes.append(outcome)

    return outcomes


def export_live_photo_videos(
    matches: list[LivePhotoMatch],
    output_dir: str | Path,
    suffix: str = "motion",
    progress_callback: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[LivePhotoOutcome]:
    """MOV를 재인코딩 없이 그대로 복사해서, 사진 파일명을 기준으로 한
    이름으로 내보낸다 — HEIC/짝 관계와 무관하게 일반 동영상 파일처럼 바로
    재생할 수 있게 하기 위함. 원본은 건드리지 않는다."""
    output_dir = Path(output_dir)
    total = len(matches)
    outcomes: list[LivePhotoOutcome] = []

    for idx, match in enumerate(matches, start=1):
        if should_cancel and should_cancel():
            break
        if progress_callback:
            progress_callback(idx, total, match.image_path.name)

        outcome = LivePhotoOutcome(match=match)
        try:
            dest = unique_recovered_path(output_dir, match.image_path.name, match.mov_path.suffix, suffix=suffix)
            shutil.copy2(match.mov_path, dest)
        except OSError as exc:
            outcome.error_message, abort = _classify_os_error(exc)
            outcomes.append(outcome)
            if abort:
                break
            continue

        outcome.output_mov_path = str(dest)
        outcome.success = True
        outcomes.append(outcome)

    return outcomes


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    """core/date_organizer.py::_unique_destination과 같은 방식 — 원본 파일명은
    최대한 그대로 유지하고, 충돌할 때만 번호를 붙인다."""
    dest = dest_dir / filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest
