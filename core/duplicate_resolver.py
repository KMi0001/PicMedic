"""
core/duplicate_resolver.py

Phase 2 "사진 정리" — 정확 중복(SHA-256 완전 일치) 그룹 안에서 "남길 파일"을
추천한다. 그룹 안 파일들은 바이트 단위로 완전히 동일하므로(내용 해시가 같음)
EXIF·해상도·용량으로는 구분할 수 없다 — 구분할 수 있는 건 파일 경로/파일명/
파일시스템 타임스탬프뿐이라 이 셋만 근거로 쓴다.

신뢰도가 낮은 경우(동점 등)는 추천하지 않고 None을 반환한다 — "자동화해도
안전한 범위"를 의도적으로 좁게 잡기 위함(PHASE2_사진정리_기획.md 참고).
gui/duplicate_screen.py는 추천이 있으면 카드의 기본 선택 라디오를 "건너뛰기"
대신 추천 파일로 바꾸는 데만 쓴다 — 실제 이동은 여전히 사용자가 "정리 실행"을
눌러야 일어난다(뷰어 우선, 실행 분리 원칙 유지).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

from models.file_info import FileInfo

_COPY_MARKER_KEYWORDS = (
    "복사본",
    "사본",
    "copy",
    "backup",
    "백업",
    "카카오톡",
    "클라우드백업",
    "kakaotalk",
)
# 끝에 " (1)", "(2)" 처럼 붙는 Windows 복사-충돌 접미사. "IMG_0284"처럼 카메라가
# 원래 붙이는 숫자 접미사(밑줄/하이픈 + 숫자)는 파일명 하나만 보고 판단하면
# 훨씬 흔해서 오탐이 심하므로, 이 괄호 형태만 "그 파일명 자체로" 복사본 신호로
# 본다. "_1", "-2" 같은 밑줄/하이픈 접미사는 _stripped_name_exists_in_group()
# 에서 그룹 문맥(짝이 되는 원본 파일이 실제로 있는지)까지 확인한 뒤에만 신호로
# 쓴다 — 아래 함수 설명 참고.
_COPY_MARKER_SUFFIX = re.compile(r"\s?\(\d+\)$")

# "_1", "-2"처럼 밑줄/하이픈 + 숫자로 끝나는 접미사 — core/date_organizer.py::
# _unique_destination, Windows 탐색기, 메신저 등이 복사 충돌 시 흔히 붙인다.
# 이 패턴만으로는 "IMG_0284"의 "_0284"와 구분이 안 되므로, 단독으로는 절대
# 안 쓰고 _stripped_name_exists_in_group()에서만 쓴다.
_COPY_MARKER_NUMBER_SUFFIX = re.compile(r"[\s_-]\d+$")


def _looks_like_copy(filename: str) -> bool:
    """파일명이 "복사본"류 이름인지 대략 판단한다(휴리스틱 — 오탐 가능성이
    있어서 단독 근거로 쓰지 않고, 그룹 안 다른 파일들과 비교하는 용도로만
    쓴다)."""
    stem = Path(filename).stem.lower()
    if any(keyword in stem for keyword in _COPY_MARKER_KEYWORDS):
        return True
    return bool(_COPY_MARKER_SUFFIX.search(stem))


def _stripped_name_exists_in_group(info: FileInfo, group: list[FileInfo]) -> bool:
    """info의 파일명에서 "_1", "-2" 같은 숫자 접미사를 뗐을 때, 그 이름을 가진
    다른 파일이 "같은 그룹 안에 실제로" 있으면 info를 복사본으로 본다 —
    a.jpg/a_1.jpg처럼 재정리 중 같은 파일이 두 번 복사돼 생긴 전형적인 경우.

    _COPY_MARKER_NUMBER_SUFFIX 패턴 자체는 "IMG_0284"(카메라가 원래 붙이는
    번호)와 구분이 안 되지만, 이 함수는 "짝이 되는 원본 파일이 그룹 안에
    실제로 존재하는지"까지 확인한다 — "IMG_0284.jpg" 하나만 있는 그룹에서는
    스트립한 이름 "IMG.jpg"가 그룹에 없으니 걸리지 않고, a.jpg가 실제로 함께
    있는 그룹에서만 a_1.jpg가 걸린다(models/scan_result.py::similar_groups()
    의 안전장치와 같은 원리 — 다만 거기는 "그룹 밖 전체 스캔"에서 짝을
    찾고, 여기는 "이미 확정된 중복 그룹 안"에서만 찾는다는 차이가 있다)."""
    stem = Path(info.filename).stem.lower()
    match = _COPY_MARKER_NUMBER_SUFFIX.search(stem)
    if not match:
        return False
    stripped = stem[: match.start()]
    ext = Path(info.filename).suffix.lower()
    return any(
        other is not info
        and Path(other.filename).suffix.lower() == ext
        and Path(other.filename).stem.lower() == stripped
        for other in group
    )


def _default_creation_time(path: str) -> Optional[float]:
    """파일시스템 생성 시각(초 단위 epoch). macOS는 st_birthtime, Windows는
    st_ctime이 실제 생성일이라 OS 분기 없이 자연스럽게 둘 다 대응된다."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return getattr(stat, "st_birthtime", stat.st_ctime)


def suggest_keep(
    group: list[FileInfo],
    *,
    creation_time_fn: Callable[[str], Optional[float]] = _default_creation_time,
) -> Optional[tuple[FileInfo, str]]:
    """중복 그룹 하나에서 남길 파일을 추천한다.

    1) 파일명에 복사본류 표시(키워드/괄호 접미사, 또는 "_1"처럼 숫자를 뗀
       이름이 그룹 안에 실제로 있는 경우)가 없는 파일이 정확히 1개면 그
       파일을 추천 — a.jpg/a_1.jpg/a_2.jpg처럼 재정리 중 같은 파일이 여러
       번 복사돼 생긴 그룹도 한 번에 처리된다.
    2) 그걸로 못 정하면(0개 또는 2개 이상), 후보들 중 파일시스템 생성일이
       유일하게 가장 이른 파일을 추천.
    3) 그것도 동점이거나 생성일을 알 수 없으면 None — 신뢰도 낮은 케이스는
       추천하지 않고 사용자가 직접 고르게 둔다.
    """
    if len(group) < 2:
        return None

    clean = [
        info
        for info in group
        if not _looks_like_copy(info.filename) and not _stripped_name_exists_in_group(info, group)
    ]
    if len(clean) == 1:
        return clean[0], "파일명에 복사본 표시(복사본/사본/카카오톡/번호 접미사 등)가 없는 유일한 파일"

    candidates = clean if clean else list(group)
    times = [(creation_time_fn(info.path), info) for info in candidates]
    if any(t is None for t, _ in times):
        return None

    times.sort(key=lambda pair: pair[0])
    earliest_time, earliest_info = times[0]
    if len(times) > 1 and times[1][0] == earliest_time:
        return None  # 동점 — 자동 추천 안 함

    return earliest_info, "파일시스템 생성일이 가장 이른 파일"


def suggest_keep_folder(
    group_list: list[list[FileInfo]],
    *,
    creation_time_fn: Callable[[str], Optional[float]] = _default_creation_time,
) -> Optional[tuple[Path, str]]:
    """폴더 단위 조합(gui/duplicate_screen.py::_cluster_by_folder)에 속한 모든
    중복 그룹이 같은 폴더를 추천할 때만 그 폴더를 추천한다 — 그룹 하나라도
    신뢰도가 낮거나(None) 다른 폴더를 추천하면 조합 전체를 추천하지 않는다
    (자동 적용 범위를 좁게 잡기 위함)."""
    folder: Optional[Path] = None
    reason: Optional[str] = None
    for group in group_list:
        rec = suggest_keep(group, creation_time_fn=creation_time_fn)
        if rec is None:
            return None
        keep_info, why = rec
        this_folder = Path(keep_info.path).parent
        if folder is None:
            folder = this_folder
            reason = why
        elif this_folder != folder:
            return None
    if folder is None:
        return None
    return folder, reason
