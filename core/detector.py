"""
core/detector.py

PRD 7장 "파일 분석 기능", FR-002 "파일 형식 탐지" 구현.

파일의 '확장자'가 아니라 파일 내부의 Signature / Magic Number를 직접 읽어
실제 파일 형식을 판별한다. HEIC/HEIF처럼 ISO-BMFF(box) 구조를 쓰는
형식은 별도 파서가 필요하다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 1. 단순 바이트 시그니처로 판별 가능한 형식 (offset 0부터 비교)
# ---------------------------------------------------------------------------
SIMPLE_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "JPEG",
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"GIF87a": "GIF",
    b"GIF89a": "GIF",
    b"BM": "BMP",
    b"II*\x00": "TIFF",   # little-endian TIFF
    b"MM\x00*": "TIFF",   # big-endian TIFF
}

# RIFF....WEBP  (RIFF는 offset 0, 'WEBP'는 offset 8)
RIFF_SIGNATURE = b"RIFF"
WEBP_MARKER = b"WEBP"

# ISO-BMFF 계열: offset 4~7 == 'ftyp', 그 뒤 4바이트가 major brand
FTYP_MARKER = b"ftyp"

# HEIC/HEIF 계열 major brand -> 사람이 읽는 형식명
HEIF_BRANDS: dict[bytes, str] = {
    b"heic": "HEIC",
    b"heix": "HEIC",
    b"heim": "HEIC",
    b"heis": "HEIC",
    b"hevc": "HEIC",   # HEVC 시퀀스
    b"hevx": "HEIC",
    b"hevm": "HEIF",
    b"hevs": "HEIF",
    b"mif1": "HEIF",   # 정지 이미지 컨테이너 (single/multi)
    b"msf1": "HEIF",
    b"avif": "AVIF",
    b"avis": "AVIF",
}

# 지원 대상 확장자 -> 그 확장자에서 "정상"으로 간주할 실제 형식들
# (MVP 범위: PRD 6장 "지원 확장자". WEBP는 복구 시 변환 대상 형식으로 쓸 수 있도록 추가 지원함.
# GIF/TIFF/BMP는 PRD 37.6 "추가 포맷 지원"에 따라 WEBP와 같은 패턴으로 스캔·변환 대상에 포함시킴)
EXPECTED_FORMAT_BY_EXTENSION: dict[str, set[str]] = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".heic": {"HEIC"},
    ".heif": {"HEIF", "HEIC"},
    ".webp": {"WEBP"},
    ".gif": {"GIF"},
    ".tiff": {"TIFF"},
    ".tif": {"TIFF"},
    ".bmp": {"BMP"},
}

# MVP에서 "알고는 있지만 지원 대상은 아닌" 확장자 (PRD 6장 "향후"). 현재는 없음 —
# 향후 새 형식(예: AVIF)을 스캔은 하되 지원 불가로 표시만 하고 싶을 때 여기에 추가한다.
FUTURE_EXTENSIONS: set[str] = set()

MVP_SUPPORTED_EXTENSIONS = set(EXPECTED_FORMAT_BY_EXTENSION.keys())

READ_HEAD_BYTES = 64  # 시그니처 판별에 필요한 최대 바이트 수


def _read_head(path: Path, n: int = READ_HEAD_BYTES) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return b""


def _detect_heif_brand(head: bytes) -> Optional[str]:
    """ISO-BMFF 'ftyp' 박스를 확인해 HEIC/HEIF/AVIF 여부 판별"""
    if len(head) < 12:
        return None
    if head[4:8] != FTYP_MARKER:
        return None
    major_brand = head[8:12].lower()
    return HEIF_BRANDS.get(major_brand)


def detect_format(path: str | Path) -> Optional[str]:
    """
    파일의 실제 형식을 시그니처 기반으로 반환한다.
    판별 불가능하면 None을 반환한다 (지원하지 않는 형식 or 이미지가 아님).
    """
    path = Path(path)
    head = _read_head(path)
    if not head:
        return None

    # 1) ISO-BMFF 계열 (HEIC/HEIF/AVIF) 우선 확인
    heif_format = _detect_heif_brand(head)
    if heif_format:
        return heif_format

    # 2) RIFF/WEBP
    if head[:4] == RIFF_SIGNATURE and head[8:12] == WEBP_MARKER:
        return "WEBP"

    # 3) 단순 바이트 시그니처
    for signature, fmt in SIMPLE_SIGNATURES.items():
        if head.startswith(signature):
            return fmt

    return None


def is_mvp_supported_extension(extension: str) -> bool:
    return extension.lower() in MVP_SUPPORTED_EXTENSIONS


def extension_matches_format(extension: str, detected_format: Optional[str]) -> bool:
    """확장자가 실제 감지된 형식과 '일치'하는 것으로 볼 수 있는지 여부"""
    if detected_format is None:
        return False
    expected = EXPECTED_FORMAT_BY_EXTENSION.get(extension.lower())
    if expected is None:
        return False
    return detected_format in expected
