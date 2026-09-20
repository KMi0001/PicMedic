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

import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import ExifTags, Image, ImageFile

try:
    import pillow_heif

    pillow_heif.register_heif_opener()  # Pillow가 HEIC/HEIF를 열 수 있게 등록
    HEIF_SUPPORT = True
except ImportError:  # pillow-heif 미설치 환경에서도 나머지 기능은 동작해야 함
    HEIF_SUPPORT = False

try:
    import imagehash

    PHASH_SUPPORT = True
except ImportError:  # imagehash 미설치 환경에서도 '유사 중복' 기능만 빠질 뿐 나머지는 동작
    PHASH_SUPPORT = False

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

# Pillow의 LOAD_TRUNCATED_IMAGES는 이미지별 옵션이 아니라 프로세스 전역 플래그다.
# gui/main_window.py는 세션 창을 여러 개 동시에 띄우는 게 설계 목표라(여러 폴더
# 동시 검사), 이 플래그를 켜고 끄는 곳이 둘 이상이면 서로의 판정을 오염시킨다:
#   - 창 A가 복구 중(플래그 True)일 때 창 B의 _try_decode 1차 시도가 들어가면,
#     잘린 파일이 그대로 읽혀 "부분_손상"이어야 할 파일이 "정상"으로 나온다.
#   - 반대로 A가 플래그를 되돌리는 순간 B의 2차 시도가 걸리면, 부분 복구가
#     가능한 파일이 "손상"(복구 불가)으로 나온다.
# 그래서 이 플래그를 만지는 모든 디코딩을 아래 decode_mode()로만 하도록 하고,
# 락으로 직렬화한다. 검사 창이 하나뿐인 보통의 경우엔 경합이 없어 성능 차이가
# 없고, 창을 여러 개 띄운 경우에만 디코딩이 순서대로 처리된다 — 그 경우는
# 지금까지 애초에 틀린 결과가 나오던 상황이라 잃는 게 없다. (2026-09-11 리뷰)
_DECODE_LOCK = threading.RLock()


@contextmanager
def decode_mode(truncated: bool):
    """LOAD_TRUNCATED_IMAGES를 원하는 값으로 고정한 채 디코딩한다. 위 _DECODE_LOCK
    주석 참고 — 이 컨텍스트 밖에서 이 플래그를 직접 건드리면 안 된다."""
    with _DECODE_LOCK:
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = truncated
        try:
            yield
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous


def _compute_file_hash(path: Path) -> Optional[str]:
    """파일 내용 SHA-256 (Phase 2 '정확 중복' 탐지용). 이미지 디코딩과 무관하게
    원본 바이트 기준이라, 디코딩 성공 여부와 상관없이 모든 파일에 매길 수 있다."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


class _DecodeResult:
    __slots__ = (
        "readable",
        "partial",
        "width",
        "height",
        "metadata",
        "captured_at",
        "perceptual_hash",
        "gps",
        "camera_make",
        "camera_model",
        "error",
    )

    def __init__(self):
        self.readable = False
        self.partial = False
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self.metadata: dict = {}
        self.captured_at: Optional[datetime] = None
        self.perceptual_hash: Optional[str] = None
        self.gps: Optional[tuple[float, float]] = None
        self.camera_make: Optional[str] = None
        self.camera_model: Optional[str] = None
        self.error: Optional[str] = None


def _try_decode(path: Path) -> _DecodeResult:
    """Pillow로 완전 디코딩을 시도하고, 실패하면 손상 허용 모드로 재시도한다."""
    result = _DecodeResult()

    # 1차: 정상 디코딩 시도. 이 판정의 핵심은 "잘린 이미지는 여기서 실패해야
    # 한다"는 것이라, 플래그가 꺼져 있음을 우연에 맡기지 않고 명시적으로 끈다
    # (_DECODE_LOCK 주석 참고 — 예전엔 다른 스레드가 켜둔 값을 그대로 물려받았다).
    try:
        with decode_mode(False), Image.open(path) as img:
            img.load()
            result.readable = True
            result.width, result.height = img.size
            result.metadata = _extract_metadata(img)
            result.captured_at = _extract_captured_at(img)
            result.perceptual_hash = _extract_perceptual_hash(img)
            result.gps = _extract_gps(img)
            result.camera_make, result.camera_model = _extract_camera_info(img)
            return result
    except Exception as first_error:
        result.error = str(first_error)

    # 2차: 잘린/손상된 이미지라도 읽을 수 있는 만큼 읽어본다 (부분 손상 판별용)
    try:
        with decode_mode(True), Image.open(path) as img:
            img.load()
            result.readable = True
            result.partial = True
            result.width, result.height = img.size
            result.metadata = _extract_metadata(img)
            result.captured_at = _extract_captured_at(img)
            result.perceptual_hash = _extract_perceptual_hash(img)
            result.gps = _extract_gps(img)
            result.camera_make, result.camera_model = _extract_camera_info(img)
    except Exception as second_error:
        result.readable = False
        result.error = result.error or str(second_error)

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


_TAG_DATE_TIME_ORIGINAL = 36867  # Exif 서브 IFD(34665) 안에 있음 — 실제 촬영 시각
_TAG_DATE_TIME = 306  # 최상위 IFD0 — 파일 저장/수정 시각에 가까움, 촬영일이 없을 때만 대체로 씀


def _extract_captured_at(img: Image.Image) -> Optional[datetime]:
    """EXIF 촬영일을 datetime으로 파싱한다(Phase 2 '날짜별 정리'). Pillow의
    Image.getexif()는 최상위 IFD0 태그만 평평하게 주고, DateTimeOriginal은
    Exif 서브 IFD 안에 있어서 get_ifd()로 따로 꺼내야 한다 — 안 그러면 항상
    None만 나온다."""
    try:
        exif = img.getexif()
        if not exif:
            return None

        raw = None
        try:
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            raw = exif_ifd.get(_TAG_DATE_TIME_ORIGINAL)
        except Exception:
            raw = None
        if not raw:
            raw = exif.get(_TAG_DATE_TIME)
        if not isinstance(raw, str):
            return None

        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def _gps_dms_to_decimal(dms, ref: str) -> float:
    """Pillow의 exif.get_ifd(GPSInfo)는 (분자, 분모) 유리수 쌍이 아니라 이미
    계산된 (도, 분, 초) 실수 3개를 그대로 준다 — 유리수 쌍으로 착각해서 처음엔
    전부 None이 나왔었다(experiments/city_organize_prototype에서 확인)."""
    degrees, minutes, seconds = dms
    value = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        value = -value
    return value


def _extract_gps(img: Image.Image) -> Optional[tuple[float, float]]:
    """EXIF GPSInfo에서 (위도, 경도)를 뽑는다(Phase 2 '도시별 정리'용).
    _extract_captured_at와 같은 이유로 get_ifd(GPSInfo)를 따로 꺼내야 한다.
    위치 정보는 민감한 개인정보이므로 여기서 뽑은 값은 core/geocoder.py를
    거쳐 화면에 도시명으로만 쓰이고, 어디로도 전송되지 않는다."""
    try:
        exif = img.getexif()
        if not exif:
            return None
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if not gps_ifd:
            return None

        lat_dms = gps_ifd.get(2)  # GPSLatitude
        lat_ref = gps_ifd.get(1)  # GPSLatitudeRef
        lon_dms = gps_ifd.get(4)  # GPSLongitude
        lon_ref = gps_ifd.get(3)  # GPSLongitudeRef
        if not (lat_dms and lat_ref and lon_dms and lon_ref):
            return None

        lat = _gps_dms_to_decimal(lat_dms, lat_ref)
        lon = _gps_dms_to_decimal(lon_dms, lon_ref)
        return (lat, lon)
    except Exception:
        return None


def _extract_camera_info(img: Image.Image) -> tuple[Optional[str], Optional[str]]:
    """EXIF Make/Model을 읽는다(Phase 2 '기기 정보'). DateTimeOriginal/GPSInfo와
    달리 이 둘은 서브 IFD가 아니라 최상위 IFD0에 바로 있는 표준 태그라
    exif.get_ifd() 없이 exif.get()만으로 꺼낼 수 있다. 스크린샷/편집 후
    재저장/다운로드한 사진 등은 이 태그가 원래 없는 경우가 많으므로, 값이
    없으면 그냥 None — "알 수 없음"으로 표시하는 건 호출하는 쪽(화면) 책임."""
    try:
        exif = img.getexif()
        if not exif:
            return None, None
        make = exif.get(271)  # Make
        model = exif.get(272)  # Model
        make = make.strip() if isinstance(make, str) and make.strip() else None
        model = model.strip() if isinstance(model, str) and model.strip() else None
        return make, model
    except Exception:
        return None, None


def _extract_perceptual_hash(img: Image.Image) -> Optional[str]:
    """이미지 지문(pHash)을 16진 문자열로 계산한다(Phase 2 '유사 중복' 탐지용
    — content_hash와 달리 리사이즈/재압축된 "거의 같은" 사진도 값이 비슷하게
    나온다). imagehash 미설치 환경에서는 이 값 없이도 나머지 기능은 그대로
    동작해야 하므로 조용히 None을 반환한다."""
    if not PHASH_SUPPORT:
        return None
    try:
        return str(imagehash.phash(img))
    except Exception:
        return None


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

    stat = path.stat()
    info.file_size = stat.st_size
    info.mtime_ns = stat.st_mtime_ns
    info.content_hash = _compute_file_hash(path)

    detected_format = detector.detect_format(path)
    info.detected_format = detected_format
    info.mime_type = MIME_TYPE_MAP.get(detected_format) if detected_format else None

    # --- 케이스 A: 시그니처로 형식을 전혀 판별하지 못한 경우 ---
    if detected_format is None:
        # detector._read_head와 같은 방식으로 연다 — 예전엔 여기만 with 없이
        # path.open()을 써서 핸들이 GC 시점까지 열린 채 남았다(수만 장 스캔에서
        # 핸들 고갈 위험). 읽기 실패는 아래 _looks_like_non_image가 빈 bytes를
        # "이미지 아님"으로 처리하므로 그대로 넘긴다.
        head = detector._read_head(path, 64)
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
            info.captured_at = decode.captured_at
            info.perceptual_hash = decode.perceptual_hash
            if decode.gps:
                info.latitude, info.longitude = decode.gps
            info.camera_make, info.camera_model = decode.camera_make, decode.camera_model
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
    info.captured_at = decode.captured_at
    info.perceptual_hash = decode.perceptual_hash
    if decode.gps:
        info.latitude, info.longitude = decode.gps
    info.camera_make, info.camera_model = decode.camera_make, decode.camera_model
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
