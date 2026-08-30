"""
core/analyzer.py

PRD 7장 "파일 분석 기능", FR-003 "이미지 유효성 검사" 구현.

detector.py 로 실제 파일 형식을 알아낸 뒤, Pillow로 실제 디코딩을 시도해
- 정상적으로 읽히는지
- 일부만 읽히는지 (부분 손상)
- 전혀 읽히지 않는지 (손상)
를 판별하고 최종적으로 FileInfo 객체 하나를 완성한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageFile

try:
    import pillow_heif

    pillow_heif.register_heif_opener()  # Pillow가 HEIC/HEIF를 열 수 있게 등록
    HEIF_SUPPORT = True
except ImportError:  # pillow-heif 미설치 환경에서도 나머지 기능은 동작해야 함
    HEIF_SUPPORT = False

from core import detector
from models.file_info import FileInfo, FileStatus, RecoveryPossibility

MIME_TYPE_MAP = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "HEIC": "image/heic",
    "HEIF": "image/heif",
    "AVIF": "image/avif",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

# 아주 작은 파일(헤더조차 없음)이나 텍스트로만 채워진 파일은
# "손상된 이미지"가 아니라 "애초에 이미지가 아닌 파일"로 본다.
MIN_PLAUSIBLE_IMAGE_BYTES = 16


class _DecodeResult:
    __slots__ = ("readable", "partial", "width", "height", "metadata", "error")

    def __init__(self):
        self.readable = False
        self.partial = False
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self.metadata: dict = {}
        self.error: Optional[str] = None


def _try_decode(path: Path) -> _DecodeResult:
    """Pillow로 완전 디코딩을 시도하고, 실패하면 손상 허용 모드로 재시도한다."""
    result = _DecodeResult()

    # 1차: 정상 디코딩 시도
    try:
        with Image.open(path) as img:
            img.load()
            result.readable = True
            result.width, result.height = img.size
            result.metadata = _extract_metadata(img)
            return result
    except Exception as first_error:
        result.error = str(first_error)

    # 2차: 잘린/손상된 이미지라도 읽을 수 있는 만큼 읽어본다 (부분 손상 판별용)
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        with Image.open(path) as img:
            img.load()
            result.readable = True
            result.partial = True
            result.width, result.height = img.size
            result.metadata = _extract_metadata(img)
    except Exception as second_error:
        result.readable = False
        result.error = result.error or str(second_error)
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False

    return result


def _extract_metadata(img: Image.Image) -> dict:
    metadata = {}
    try:
        exif = img.getexif()
        if exif:
            # 사람이 읽을 수 있는 값만 남기고, bytes 등은 문자열로 변환
            for tag_id, value in exif.items():
                try:
                    metadata[str(tag_id)] = value if isinstance(value, (int, float, str)) else str(value)
                except Exception:
                    continue
    except Exception:
        pass
    return metadata


def _looks_like_non_image(head: bytes) -> bool:
    """
    파일 앞부분이 사람이 읽는 텍스트에 가까우면 '이미지가 아닌 파일'로 추정한다.

    이 함수는 시그니처 탐지가 이미 실패한 경우에만 호출되므로,
    실제 (손상된) 이미지 바이너리라면 유효한 UTF-8로 디코딩될 가능성이 낮다.
    반대로 한글/영문 등 텍스트 파일은 UTF-8로 정상 디코딩된다.
    """
    if not head:
        return True

    # 흔히 쓰이는 텍스트 인코딩들을 순서대로 시도한다.
    # (Windows 한글 환경은 기본적으로 cp949/euc-kr로 텍스트를 저장하는 경우가 많다.)
    TEXT_ENCODINGS = ("utf-8", "cp949", "euc-kr")
    # 멀티바이트 문자는 head를 딱 잘랐을 때 문자 중간에서 끊길 수 있으므로
    # 끝에서 몇 바이트씩 잘라내며 디코딩을 시도한다.
    for encoding in TEXT_ENCODINGS:
        for trim in range(0, 4):
            candidate = head[: len(head) - trim] if trim else head
            if not candidate:
                break
            try:
                candidate.decode(encoding)
                return True
            except UnicodeDecodeError:
                continue

    # 위 인코딩으로도 안 되지만 ASCII 출력 가능 문자 비율이 매우 높은 경우도 텍스트로 간주
    printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(head) > 0.9


def analyze_file(path: str | Path) -> FileInfo:
    path = Path(path)
    filename = path.name
    extension = path.suffix.lower()

    info = FileInfo(
        path=str(path),
        filename=filename,
        extension=extension,
    )

    if not path.exists() or not path.is_file():
        info.status = FileStatus.UNKNOWN
        info.error_message = "파일을 찾을 수 없습니다."
        return info

    info.file_size = path.stat().st_size

    detected_format = detector.detect_format(path)
    info.detected_format = detected_format
    info.mime_type = MIME_TYPE_MAP.get(detected_format) if detected_format else None

    # --- 케이스 A: 시그니처로 형식을 전혀 판별하지 못한 경우 ---
    if detected_format is None:
        head = path.open("rb").read(64)
        if info.file_size < MIN_PLAUSIBLE_IMAGE_BYTES or _looks_like_non_image(head):
            info.status = FileStatus.NOT_AN_IMAGE
            info.readable = False
            info.recoverable = RecoveryPossibility.NOT_APPLICABLE
            info.error_message = "이미지 파일로 보이지 않습니다."
            return info

        if not detector.is_mvp_supported_extension(extension) and extension not in detector.FUTURE_EXTENSIONS:
            info.status = FileStatus.NOT_AN_IMAGE
            info.error_message = "지원 대상 확장자가 아니며 이미지 시그니처도 없습니다."
            return info

        # 확장자는 이미지처럼 보이는데 시그니처가 없다 -> 헤더 손상 가능성. 그래도 디코딩을 시도.
        decode = _try_decode(path)
        if decode.readable and not decode.partial:
            info.status = FileStatus.CORRUPTED  # 헤더는 깨졌지만 우연히 읽힌 경우도 '손상'으로 보수적 분류
        elif decode.readable and decode.partial:
            info.status = FileStatus.PARTIAL_CORRUPTION
            info.width, info.height = decode.width, decode.height
            info.metadata = decode.metadata
            info.recoverable = RecoveryPossibility.PARTIALLY_RECOVERABLE
        else:
            info.status = FileStatus.CORRUPTED
            info.recoverable = RecoveryPossibility.NOT_RECOVERABLE
        info.readable = decode.readable
        info.error_message = decode.error
        return info

    # --- 케이스 B: 시그니처로 형식이 확인된 경우 ---
    # WEBP/GIF/TIFF/BMP는 입력으로 스캔될 때뿐 아니라 복구 시 변환 대상 형식으로도 쓰이므로
    # 지원 형식에 포함한다 (PRD 37.6 "추가 포맷 지원").
    is_supported_format = detected_format in {"JPEG", "PNG", "HEIC", "HEIF", "WEBP", "GIF", "TIFF", "BMP"}
    info.is_mismatched = not detector.extension_matches_format(extension, detected_format)

    if not is_supported_format:
        # AVIF 등 아직 지원하지 않는 형식
        info.status = FileStatus.UNSUPPORTED
        info.recoverable = RecoveryPossibility.NOT_APPLICABLE
        info.error_message = f"'{detected_format}' 형식은 현재 지원되지 않습니다."
        return info

    if detected_format in ("HEIC", "HEIF") and not HEIF_SUPPORT:
        # 디코더가 없어도 '형식 불일치'라는 사실 자체는 알려줄 수 있다.
        info.status = FileStatus.MISMATCH if info.is_mismatched else FileStatus.UNKNOWN
        info.error_message = "HEIC/HEIF 디코더(pillow-heif)가 설치되어 있지 않아 내용 검증은 생략했습니다."
        info.recoverable = RecoveryPossibility.RECOVERABLE if info.is_mismatched else RecoveryPossibility.NOT_APPLICABLE
        return info

    decode = _try_decode(path)
    info.readable = decode.readable
    info.width, info.height = decode.width, decode.height
    info.metadata = decode.metadata
    info.error_message = decode.error

    if decode.readable and not decode.partial:
        info.status = FileStatus.MISMATCH if info.is_mismatched else FileStatus.NORMAL
        info.recoverable = (
            RecoveryPossibility.RECOVERABLE if info.is_mismatched else RecoveryPossibility.NOT_APPLICABLE
        )
    elif decode.readable and decode.partial:
        info.status = FileStatus.PARTIAL_CORRUPTION
        info.recoverable = RecoveryPossibility.PARTIALLY_RECOVERABLE
    else:
        info.status = FileStatus.CORRUPTED
        info.recoverable = RecoveryPossibility.NOT_RECOVERABLE

    return info
