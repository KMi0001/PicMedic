"""
core/converter.py

PRD 10장 "복구 기능", 11장 "이미지 변환", 15장 "복구 결과 검증" 구현.

원칙(PRD 24장 "안전성"):
    Never modify original files by default.
    -> 이 모듈은 항상 output_dir 아래에 '새 파일'을 만들고, 원본은 절대 건드리지 않는다.
"""

from __future__ import annotations

import errno
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFile

from core.analyzer import analyze_file, HEIF_SUPPORT
from models.file_info import FileInfo, FileStatus
from utils import logger
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
        # 이 플래그는 Pillow 프로세스 전역 설정이라, try/finally로 반드시 되돌려놓는다.
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            with Image.open(info.path) as img:
                img.load()
                if target_format not in ALPHA_CAPABLE_FORMATS and img.mode in ("RGBA", "P", "LA"):
                    # 출력 형식이 알파 채널을 지원하지 않으면 저장 전에 RGB로 눌러야 한다 (예: JPEG)
                    img = img.convert("RGB")
                save_kwargs = {}
                if target_format in ("JPEG", "WEBP"):
                    save_kwargs["quality"] = quality
                img.save(output_path, format=target_format, **save_kwargs)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
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
) -> list[RecoveryOutcome]:
    """PRD FR-005 '일괄 복구'. suffix는 복구 파일명 뒤에 붙는 문구 (기본값 'recovered')."""
    output_dir = Path(output_dir)
    outcomes = []
    total = len(files)
    for idx, info in enumerate(files, start=1):
        try:
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
    return outcomes
