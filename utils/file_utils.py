"""
utils/file_utils.py

PRD 23.6 "동일 파일명 존재" 처리:
IMG_001.jpg -> IMG_001_recovered.jpg -> IMG_001_recovered_2.jpg ...

파일명에 붙는 문구("recovered")는 Recovery 화면에서 사용자가 자유롭게 바꿀 수 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_SUFFIX = "recovered"
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_filename_part(text: str, fallback: str = DEFAULT_SUFFIX) -> str:
    """파일명에 쓸 수 없는 문자를 제거한다. 결과가 비어 있으면 fallback을 쓴다."""
    cleaned = _INVALID_FILENAME_CHARS.sub("", text).strip()
    return cleaned or fallback


def format_file_size(num_bytes: int) -> str:
    """사람이 읽기 쉬운 파일 크기 문자열로 바꾼다 (예: 1536 -> '1.5 KB')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def reclaimable_bytes(groups) -> int:
    """중복/유사 그룹마다 가장 큰 파일 하나만 남긴다고 쳤을 때 줄어드는 용량의
    합(최대치). 그룹은 FileInfo 목록. "지금 확보됐다"가 아니라 "이만큼 겹쳐
    있다"는 정보용 — 정리해도 임시휴지통으로 옮길 뿐이라 디스크 용량은 그
    폴더를 직접 비우기 전까진 그대로다(2026-09-23, 사용자 결정: 앱이 휴지통
    비우기로 유도하지 않도록 숫자는 사실만 보여준다)."""
    return sum(
        sum(info.file_size for info in group) - max(info.file_size for info in group)
        for group in groups
        if len(group) > 1
    )


def unique_recovered_path(
    output_dir: Path, base_filename: str, new_extension: str, suffix: str = DEFAULT_SUFFIX
) -> Path:
    """
    output_dir 안에서 base_filename(원본 파일명, 확장자 제외)에 대해
    충돌하지 않는 '..._{suffix}(.ext)' 경로를 만들어 반환한다.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(base_filename).stem
    ext = new_extension if new_extension.startswith(".") else f".{new_extension}"
    suffix = sanitize_filename_part(suffix)

    candidate = output_dir / f"{stem}_{suffix}{ext}"
    if not candidate.exists():
        return candidate

    n = 2
    while True:
        candidate = output_dir / f"{stem}_{suffix}_{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1
