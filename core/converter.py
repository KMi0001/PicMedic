"""
core/converter.py

PRD 10장 "복구 기능", 11장 "이미지 변환", 15장 "복구 결과 검증" 구현.

원칙(PRD 24장 "안전성"):
    Never modify original files by default.
    -> 이 모듈은 기본적으로 항상 output_dir 아래에 '새 파일'을 만들고, 원본은 절대
       건드리지 않는다. replace_original=True(사용자가 명시적으로 켠 경우에만,
       2026-09-10 요청)일 때만 예외로, 원본을 그 폴더의 임시휴지통으로 옮기고
       결과물이 원본이 있던 자리를 대신한다 — _recover_file_replacing_original 참고.
"""

from __future__ import annotations

import dataclasses
import errno
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from core.analyzer import analyze_file, HEIF_SUPPORT, decode_mode
from models.file_info import FileInfo, FileStatus
from utils import logger, trash
from utils.file_utils import unique_recovered_path

# 파일 잠금(다른 프로그램에서 사용 중)은 Windows에서 별도 예외 타입이 없고
# PermissionError(winerror=32)로 온다. 저장 공간 부족은 winerror=112 또는
# errno.ENOSPC로 온다 (플랫폼에 따라 다름).
_WINERROR_FILE_LOCKED = 32
_WINERROR_DISK_FULL = 112


def _classify_os_error(exc: OSError, fallback_prefix: str) -> tuple[str, bool]:
    """PRD 23장 문구로 변환한다. (사용자에게 보여줄 메시지, 배치 전체를 중단해야 하는지).

    23.1/23.3/23.5에 해당하지 않는 그 외 OSError(예: 완전 손상 파일의 디코딩 실패)는
    기존과 같은 형식(f"{fallback_prefix}: {exc}")으로 남긴다.
    """
    winerror = getattr(exc, "winerror", None)

    if winerror == _WINERROR_FILE_LOCKED:
        return "다른 프로그램에서 사용 중인 파일입니다.", False
    if isinstance(exc, PermissionError):
        return "이 파일에 접근할 수 없습니다.", False
    if winerror == _WINERROR_DISK_FULL or exc.errno == errno.ENOSPC:
        # 23.5: 현재까지 성공한 파일은 유지하고, 이후 작업은 중단한다.
        return "복구 파일을 저장할 공간이 부족합니다.", True

    return f"{fallback_prefix}: {exc}", False


EXTENSION_BY_FORMAT = {
    "HEIC": ".heic",
    "HEIF": ".heif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "TIFF": ".tiff",
    "BMP": ".bmp",
}

# '형식 변환'에서 사용자가 고를 수 있는 출력 형식 (HEIC/HEIF는 변환 대상으로 쓸 일이 없어 제외).
# GIF/TIFF/BMP는 PRD 37.6에 따라 WEBP와 같은 패턴으로 추가함.
CONVERT_TARGET_FORMATS = ["JPEG", "PNG", "WEBP", "GIF", "TIFF", "BMP"]

# 알파(투명) 채널을 지원하는 출력 형식. 이 목록에 없으면 저장 전에 RGB로 눌러야 한다.
# GIF/BMP는 Pillow에서 RGBA 저장이 불안정해 안전하게 RGB로 눌러서 저장한다.
ALPHA_CAPABLE_FORMATS = {"PNG", "WEBP", "TIFF"}

DEFAULT_CONVERT_FORMAT = "JPEG"


class RecoveryMode(str, Enum):
    RESTORE_EXTENSION = "확장자_복원"  # 실제 형식에 맞춰 확장자만 되돌림 (Screen 04 'HEIC로 복구')
    CONVERT = "형식_변환"              # 내용을 디코딩해 원하는 형식으로 다시 저장 (Screen 04 '형식 변환')


@dataclass
class RecoveryOutcome:
    original: FileInfo
    mode: RecoveryMode
    output_path: Optional[str] = None
    success: bool = False
    verified: bool = False
    error_message: Optional[str] = None
    target_format: Optional[str] = None  # CONVERT 모드일 때 실제로 저장한 형식 (JPEG/PNG/WEBP)
    abort_batch: bool = False  # PRD 23.5: 저장 공간 부족 시 이 파일 이후로는 배치를 중단해야 함
    skipped: bool = False  # 처리할 내용이 없어 건너뛴 경우 (예: 이미 정상인 파일의 확장자 복원)
    # replace_original=True로 성공했을 때만 채워짐 — 원본이 실제로 옮겨간 임시휴지통 경로.
    # 호출부가 나중에(예: 취소 후 "삭제하고 되돌리기") trash.restore_from_trash()로 원본을
    # 되돌려야 할 수 있어서, 어느 경로를 되돌릴지 정확히 알 수 있게 기록해둔다.
    replaced_original_trash_path: Optional[str] = None

    @property
    def label(self) -> str:
        if self.skipped:
            return "건너뜀"
        if self.success and self.verified:
            return "성공"
        if self.success and not self.verified:
            return "부분_성공"
        return "실패"


def _verify(path: Path) -> tuple[bool, Optional[str]]:
    """복구 후 재검증: 실제로 다시 정상적으로 읽히는지 확인한다 (PRD 15장)."""
    info = analyze_file(path)
    if info.status == FileStatus.NORMAL:
        return True, None
    return False, f"재검증 결과 상태={info.status.value}"


def restore_extension(info: FileInfo, output_dir: Path, suffix: str = "recovered") -> RecoveryOutcome:
    """확장자만 실제 형식에 맞게 복원한다 (원본은 그대로 두고 새 파일로 복사)."""
    outcome = RecoveryOutcome(original=info, mode=RecoveryMode.RESTORE_EXTENSION)

    new_ext = EXTENSION_BY_FORMAT.get(info.detected_format or "")
    if not new_ext:
        outcome.error_message = f"'{info.detected_format}' 형식은 확장자 복원을 지원하지 않습니다."
        return outcome

    try:
        output_path = unique_recovered_path(output_dir, info.filename, new_ext, suffix=suffix)
        shutil.copy2(info.path, output_path)  # 원본 보호: copy이지 move가 아님
    except OSError as exc:
        outcome.error_message, outcome.abort_batch = _classify_os_error(exc, "파일 복사 실패")
        return outcome

    outcome.output_path = str(output_path)
    outcome.success = True
    outcome.verified, verify_err = _verify(output_path)
    if verify_err:
        outcome.error_message = verify_err
    return outcome


def convert_to_format(
    info: FileInfo,
    output_dir: Path,
    target_format: str = DEFAULT_CONVERT_FORMAT,
    quality: int = 90,
    suffix: str = "recovered",
) -> RecoveryOutcome:
    """실제 이미지 내용을 디코딩하여 지정한 형식(JPEG/PNG/WEBP)으로 다시 저장한다."""
    outcome = RecoveryOutcome(original=info, mode=RecoveryMode.CONVERT, target_format=target_format)

    ext = EXTENSION_BY_FORMAT.get(target_format)
    if not ext or target_format not in CONVERT_TARGET_FORMATS:
        outcome.error_message = f"지원하지 않는 변환 형식입니다: {target_format}"
        return outcome

    if info.detected_format in ("HEIC", "HEIF") and not HEIF_SUPPORT:
        outcome.error_message = "HEIC/HEIF 디코더(pillow-heif)가 설치되어 있지 않습니다."
        return outcome

    try:
        output_path = unique_recovered_path(output_dir, info.filename, ext, suffix=suffix)
        # 부분 손상 파일(analyzer가 "부분_손상/부분_복구_가능"으로 판정한 것)도 시도는 되게
        # 하려면, 분석 때와 마찬가지로 잘린 이미지를 끝까지 읽어보는 모드를 켜야 한다.
        # 이 플래그는 Pillow 프로세스 전역 설정이라 직접 만지지 않고 analyzer의
        # decode_mode()로만 켠다 — 여기서 켜둔 동안 다른 창의 검사가 이 값을
        # 물려받아 잘린 파일을 "정상"으로 오판하던 문제가 있었다(core/analyzer.py의
        # _DECODE_LOCK 주석 참고, 2026-09-11).
        with decode_mode(True), Image.open(info.path) as img:
            img.load()
            if target_format not in ALPHA_CAPABLE_FORMATS and img.mode in ("RGBA", "P", "LA"):
                # 출력 형식이 알파 채널을 지원하지 않으면 저장 전에 RGB로 눌러야 한다 (예: JPEG)
                img = img.convert("RGB")
            save_kwargs = {}
            if target_format in ("JPEG", "WEBP"):
                save_kwargs["quality"] = quality
            img.save(output_path, format=target_format, **save_kwargs)
    except OSError as exc:
        outcome.error_message, outcome.abort_batch = _classify_os_error(exc, "변환 실패")
        return outcome
    except Exception as exc:
        outcome.error_message = f"변환 실패: {exc}"
        return outcome

    outcome.output_path = str(output_path)
    outcome.success = True
    outcome.verified, verify_err = _verify(output_path)
    if verify_err:
        outcome.error_message = verify_err
    return outcome


def _recover_file_replacing_original(
    info: FileInfo,
    mode: RecoveryMode,
    target_format: str = DEFAULT_CONVERT_FORMAT,
    quality: int = 90,
) -> RecoveryOutcome:
    """"원본 삭제" 옵션(사용자가 명시적으로 켠 경우에만)을 위한 경로 — 원본을
    그 파일이 있던 폴더의 임시휴지통으로 먼저 옮겨 자리를 비운 뒤, 그 자리에
    (원본과 같은 폴더, suffix 없이) 복구/변환 결과를 새로 저장해서 "대체"한다.
    실패하면 옮겨둔 원본을 즉시 되돌린다 — 사진이 폴더에서 사라져 보이기만
    하고 아무것도 안 남는 순간이 없게 하기 위함."""
    original_path = Path(info.path)
    output_dir = original_path.parent
    try:
        trashed_path = trash.move_to_trash(original_path, reason=f"{mode.value} — 원본 대체")
    except OSError as exc:
        return RecoveryOutcome(
            original=info, mode=mode, error_message=f"원본을 임시휴지통으로 옮기지 못해 중단했습니다: {exc}"
        )

    # 원본은 이제 trashed_path에 있으므로, 복구/변환은 거기서 읽어야 한다 —
    # info는 화면에 보여줄 "원래 경로"를 유지해야 하니 얕은 복사로 path만 바꾼다.
    source_info = dataclasses.replace(info, path=str(trashed_path))
    try:
        outcome = recover_file(source_info, mode, output_dir, suffix="", target_format=target_format, quality=quality)
    except Exception as exc:
        # recover_file()이 자기 안에서 처리하는 OSError(파일 잠금/용량 부족 등)가
        # 아니라 예상 못한 예외를 던지면, 이 함수를 감싸는 recover_batch()의
        # try/except까지 그대로 새어나가 아래 "실패 시 원본 즉시 복원" 로직이
        # 통째로 건너뛰어진다 — 원본이 임시휴지통에 남은 채 아무도 되돌리지
        # 않는 상태(2026-09-11, 테스트로 실제 재현·확인). 이 함수의 계약(문서
        # 상단 설명)은 "실패하면 옮겨둔 원본을 즉시 되돌린다"이므로, 예외
        # 경로도 실패로 취급해 같은 보장을 지킨다.
        outcome = RecoveryOutcome(original=info, mode=mode, error_message=f"복구 중 예상하지 못한 오류: {exc}")
        try:
            trash.restore_from_trash(trashed_path)
        except (ValueError, OSError):
            pass  # 복원까지 실패해도 원본 자체는 임시휴지통에 안전하게 남아있다(수동 복원 가능)
        return outcome
    outcome.original = info

    if outcome.success and outcome.output_path:
        # unique_recovered_path는 suffix가 비어도 항상 "_recovered" 같은 기본
        # 문구를 붙인다(다른 흐름에서 suffix 입력칸이 실수로 비었을 때 원본과
        # 이름이 겹치는 걸 막기 위한 안전장치라 건드리지 않는다) — 여기서는
        # 원본을 이미 치웠으니 굳이 그 문구가 필요 없어, 결과 자체를 "원본
        # 이름 + 새 확장자"로 다시 이름 붙여서 진짜 "그 자리를 대신"하게 한다.
        produced = Path(outcome.output_path)
        desired = output_dir / f"{original_path.stem}{produced.suffix}"
        if desired != produced and not desired.exists():
            produced.rename(desired)
            outcome.output_path = str(desired)
        outcome.replaced_original_trash_path = str(trashed_path)

    if not outcome.success:
        try:
            trash.restore_from_trash(trashed_path)
        except (ValueError, OSError):
            pass  # 복원까지 실패해도 원본 자체는 임시휴지통에 안전하게 남아있다(수동 복원 가능)
    return outcome


def recover_file(
    info: FileInfo,
    mode: RecoveryMode,
    output_dir: str | Path,
    suffix: str = "recovered",
    target_format: str = DEFAULT_CONVERT_FORMAT,
    quality: int = 90,
) -> RecoveryOutcome:
    output_dir = Path(output_dir)
    if mode == RecoveryMode.RESTORE_EXTENSION:
        if info.status == FileStatus.NORMAL:
            # 확장자와 실제 형식이 이미 일치하는 정상 파일은 복원할 내용이 없다 — 그대로
            # 복사해봤자 의미 없는 중복 파일만 생기므로 건너뛴다 (PRD_MVP우선순위.md '갭 #11').
            # 반대로 '형식 변환' 모드는 정상 파일에도 쓸 수 있는 의도된 기능이라 건너뛰지 않는다.
            return RecoveryOutcome(
                original=info,
                mode=mode,
                skipped=True,
                error_message="이미 정상 파일이라 복원할 내용이 없습니다.",
            )
        return restore_extension(info, output_dir, suffix=suffix)
    elif mode == RecoveryMode.CONVERT:
        return convert_to_format(info, output_dir, target_format=target_format, suffix=suffix, quality=quality)
    raise ValueError(f"알 수 없는 복구 방식: {mode}")


def recover_batch(
    files: list[FileInfo],
    mode: RecoveryMode,
    output_dir: str | Path,
    progress_callback=None,  # (current, total, filename) -> None
    suffix: str = "recovered",
    target_format: str = DEFAULT_CONVERT_FORMAT,
    quality: int = 90,
    should_cancel: Optional[Callable[[], bool]] = None,  # core/scanner.py::scan_paths와 같은 취소 방식
    replace_original: bool = False,  # True면 output_dir/suffix를 무시하고 _recover_file_replacing_original 사용
) -> list[RecoveryOutcome]:
    """PRD FR-005 '일괄 복구'. suffix는 복구 파일명 뒤에 붙는 문구 (기본값 'recovered').
    replace_original=True면 파일마다 원본이 있던 폴더에 결과물을 저장하고 원본은
    그 폴더의 임시휴지통으로 옮긴다(사용자가 명시적으로 켠 경우에만 — 기본 False)."""
    output_dir = Path(output_dir) if output_dir else None
    outcomes = []
    total = len(files)
    for idx, info in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        try:
            if replace_original:
                outcome = _recover_file_replacing_original(info, mode, target_format=target_format, quality=quality)
            else:
                outcome = recover_file(
                    info, mode, output_dir, suffix=suffix, target_format=target_format, quality=quality
                )
        except Exception as exc:  # 개별 파일 실패가 전체 배치를 막지 않도록
            outcome = RecoveryOutcome(original=info, mode=mode, error_message=str(exc))
        outcomes.append(outcome)
        logger.log_recovery(outcome)
        if progress_callback:
            progress_callback(idx, total, info.filename)
        if outcome.abort_batch:
            # PRD 23.5: 저장 공간 부족 등으로 더 진행해도 소용없는 경우, 지금까지 성공한
            # 파일은 그대로 두고 나머지 파일 처리는 건너뛴다(전체 배치를 여기서 중단).
            break
    # replace_original=True 배치는 파일마다 utils/trash.move_to_trash()를 불러
    # 원본을 임시휴지통으로 옮기는데, 그 매니페스트 쓰기는 메모리에 모아뒀다가
    # 나중에 한 번에 쓰는 방식으로 바뀌었다(gui/trash_worker.py와 같은 이유,
    # 2026-09-17). replace_original이 아니면 아무것도 안 쌓였으니 그냥 no-op.
    trash.flush_trash_manifests()
    return outcomes
