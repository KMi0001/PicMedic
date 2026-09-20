"""
core/session_store.py

작업 자동 저장/불러오기 (2026-09-20, 사용자 요청) — 검사 결과 창을 닫을 때
그 폴더의 검사 결과(FileInfo 목록) + AI 카테고리 분류 결과 + 사용자가 직접
옮긴 카테고리 내역을 파일 하나로 저장해 두고, 같은 폴더를 다시 검사하면
core/scanner.py::scan_paths_incremental이 이 저장본을 바탕으로 "그대로인
사진은 재사용, 추가/변경된 사진만 새로 분석"한다(사진 3만 장 기준 전체
검사 + AI 분류가 수십 분 걸리는 걸 변경분만큼으로 줄이려는 것).

저장 위치는 사용자 데이터 폴더의 sessions/ — 선택한 경로 묶음마다 파일
하나(경로들을 정규화해 해시한 이름). 같은 폴더를 다시 검사하면 같은
파일을 덮어쓴다.

core/에는 Qt 의존을 두지 않는다(utils/logger.py 주석 참고) — 여기도 순수
Python만 쓴다. 저장은 창 닫기를 막지 않도록 백그라운드 스레드에서 하고,
임시 파일에 쓴 뒤 교체해서 도중에 앱이 죽어도 이전 저장본이 깨지지 않는다.
"""

from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from core.category_finder import CATEGORIES
from models.file_info import FileInfo, FileStatus, RecoveryPossibility
from utils.logger import _user_data_dir

FORMAT_VERSION = 1
SESSION_DIR = _user_data_dir() / "sessions"

# 저장하지 않는 FileInfo 필드 — metadata(EXIF 원문)는 앱 어디서도 읽지 않는데
# 사진당 수 KB라 저장본만 부풀리고, inferred_*는 ScanResult.city_groups()가 매번
# 새로 계산하는 파생값이라 옛 값을 들고 있으면 오히려 어긋난다.
_SKIPPED_FIELDS = {"metadata", "inferred_latitude", "inferred_longitude", "location_inferred_from"}

_ENUM_FIELDS = {"status": FileStatus, "recoverable": RecoveryPossibility}


def norm_path(path: str | Path) -> str:
    """경로 비교용 정규화 — Windows는 대소문자를 구분하지 않으므로 normcase까지."""
    return os.path.normcase(str(path))


def session_key(paths: Iterable[str | Path]) -> str:
    """사용자가 고른 경로(들)로 저장 파일 이름을 만든다 — 같은 폴더(들)를
    다시 고르면 같은 키."""
    normalized = []
    for p in paths:
        try:
            normalized.append(norm_path(Path(p).resolve()))
        except OSError:
            normalized.append(norm_path(p))
    joined = "\n".join(sorted(set(normalized)))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:20]


def session_file(paths: Iterable[str | Path]) -> Path:
    return SESSION_DIR / f"{session_key(paths)}.json.gz"


def category_signature() -> str:
    """카테고리 프롬프트/임계값이 바뀌면 옛 AI 분류 결과는 더 이상 믿을 수
    없다 — 저장할 때의 서명과 불러올 때의 서명이 다르면 분류 결과는 버린다."""
    payload = {
        cat_id: [cat.positive_prompts, cat.negative_prompts, cat.threshold]
        for cat_id, cat in sorted(CATEGORIES.items())
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# --- FileInfo <-> dict --------------------------------------------------

def file_info_to_dict(info: FileInfo) -> dict:
    out: dict = {}
    for f in dataclasses.fields(info):
        if f.name in _SKIPPED_FIELDS:
            continue
        value = getattr(info, f.name)
        if f.default is not dataclasses.MISSING and value == f.default:
            continue  # 기본값이면 생략 — 저장본 크기를 줄인다
        if f.name in _ENUM_FIELDS:
            value = value.value
        elif isinstance(value, datetime):
            value = value.isoformat()
        out[f.name] = value
    return out


def file_info_from_dict(data: dict) -> FileInfo:
    kwargs: dict = {}
    for f in dataclasses.fields(FileInfo):
        if f.name in _SKIPPED_FIELDS or f.name not in data:
            continue
        value = data[f.name]
        if f.name in _ENUM_FIELDS:
            value = _ENUM_FIELDS[f.name](value)
        elif f.name == "captured_at" and value is not None:
            value = datetime.fromisoformat(value)
        kwargs[f.name] = value
    return FileInfo(**kwargs)


# --- 저장본 -------------------------------------------------------------

@dataclass
class SavedSession:
    origin_paths: list[str]
    files: list[FileInfo]
    # path -> AI가 매칭한 [(category_id, confidence), ...] — 분류가 끝난 사진만
    # 키가 있다(빈 리스트 = 분류했는데 어느 카테고리도 아니었음). 사용자
    # 수동 이동은 여기에 섞지 않고 아래 overrides로 따로 둔다.
    categories: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # path -> {category_id: True(강제로 넣음) | False(강제로 뺌)}
    overrides: dict[str, dict[str, bool]] = field(default_factory=dict)

    def remap_paths(self, moved: dict[str, str]) -> None:
        """사용자가 사진을 다른 폴더로 옮긴 걸 알아챘을 때(old -> new) 카테고리·
        수동 이동 내역을 새 경로로 옮겨 단다."""
        for table in (self.categories, self.overrides):
            for old, new in moved.items():
                if old in table:
                    table[new] = table.pop(old)

    def drop_categories(self, paths: Iterable[str]) -> None:
        """내용이 바뀐 사진은 옛 AI 분류를 버린다(수동 이동 내역은 사용자의
        판단이라 남긴다)."""
        for p in paths:
            self.categories.pop(p, None)


def _serialize(origin_paths, files, categories, overrides) -> dict:
    return {
        "version": FORMAT_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "category_signature": category_signature(),
        "origin_paths": [str(p) for p in origin_paths],
        "files": [file_info_to_dict(f) for f in files],
        "categories": {p: [[c, conf] for c, conf in matches] for p, matches in categories.items()},
        "overrides": overrides,
    }


def save_session(
    origin_paths: list[str],
    files: list[FileInfo],
    categories: dict[str, list[tuple[str, float]]],
    overrides: dict[str, dict[str, bool]],
) -> None:
    """저장본을 쓴다 — 실패해도(디스크 가득, 권한 등) 조용히 넘어간다. 자동
    저장은 부가 기능이라 그것 때문에 창이 안 닫히거나 예외가 나면 안 된다."""
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        target = session_file(origin_paths)
        payload = json.dumps(_serialize(origin_paths, files, categories, overrides), ensure_ascii=False, separators=(",", ":"))
        fd, tmp_name = tempfile.mkstemp(dir=SESSION_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=3) as gz:
                gz.write(payload.encode("utf-8"))
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001
        return


def save_session_in_background(
    origin_paths: list[str],
    files: list[FileInfo],
    categories: dict[str, list[tuple[str, float]]],
    overrides: dict[str, dict[str, bool]],
) -> threading.Thread:
    """창 닫기를 막지 않도록 백그라운드에서 저장한다. 데몬 스레드가 아니라서
    앱 종료 시 저장이 끝날 때까지는 프로세스가 기다려 준다. 넘기는 값은
    호출 쪽에서 더 안 바꾸는 것(닫히는 창의 스냅샷)이어야 한다."""
    thread = threading.Thread(
        target=save_session, args=(origin_paths, files, categories, overrides), name="picmedic-session-save"
    )
    thread.start()
    return thread


def load_session(origin_paths: Iterable[str | Path]) -> Optional[SavedSession]:
    """같은 경로 묶음의 저장본을 읽는다. 없거나 깨졌거나 형식 버전이 다르면
    None — 호출하는 쪽은 그냥 처음부터 검사하면 된다."""
    origin_paths = list(origin_paths)
    try:
        target = session_file(origin_paths)
        if not target.is_file():
            return None
        with gzip.open(target, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        if data.get("version") != FORMAT_VERSION:
            return None
        files = [file_info_from_dict(d) for d in data["files"]]
        overrides = {
            p: {c: bool(v) for c, v in per.items() if c in CATEGORIES}
            for p, per in data.get("overrides", {}).items()
        }
        categories: dict[str, list[tuple[str, float]]] = {}
        if data.get("category_signature") == category_signature():
            categories = {
                p: [(c, float(conf)) for c, conf in matches if c in CATEGORIES]
                for p, matches in data.get("categories", {}).items()
            }
        return SavedSession(
            origin_paths=[str(p) for p in data.get("origin_paths", [])],
            files=files,
            categories=categories,
            overrides=overrides,
        )
    except Exception:  # noqa: BLE001 - 깨진 저장본이 검사를 막으면 안 된다
        return None
