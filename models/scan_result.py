"""
models/scan_result.py

PRD 27장 "데이터 모델" ScanResult 구현.
폴더 검사 한 번의 전체 결과(집계 + 개별 파일 목록)를 담는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from models.file_info import FileInfo, FileStatus

# 끝에 "_1", "-2", " (3)" 처럼 붙는 복사 접미사 — core/date_organizer.py::
# _unique_destination이나 Windows 탐색기가 이런 식으로 이름을 붙인다. 이
# 모양만 보고 판단하면 "IMG_0284"처럼 카메라가 원래 붙이는 번호까지 오탐하므로,
# 접미사를 뗀 이름이 "실제로 존재하는 다른 파일"과 일치할 때만 신호로 쓴다
# (_similar_name_key 참고) — 그러면 우연히 모양만 비슷한 파일명은 걸리지 않는다.
_COPY_SUFFIX_PATTERN = re.compile(r"[ _-]\(?(\d+)\)?$")

_COUNTER_BY_STATUS = {
    FileStatus.NORMAL: "normal",
    FileStatus.MISMATCH: "mismatch",
    FileStatus.PARTIAL_CORRUPTION: "partial_corruption",
    FileStatus.CORRUPTED: "corrupted",
    FileStatus.UNSUPPORTED: "unsupported",
    FileStatus.NOT_AN_IMAGE: "not_an_image",
    FileStatus.RECOVERED: "recovered",
}


@dataclass
class ScanResult:
    total: int = 0
    normal: int = 0
    mismatch: int = 0
    partial_corruption: int = 0
    corrupted: int = 0
    unsupported: int = 0
    not_an_image: int = 0
    recovered: int = 0
    files: list[FileInfo] = field(default_factory=list)

    def add(self, info: FileInfo) -> None:
        self.total += 1
        self.files.append(info)
        counter = _COUNTER_BY_STATUS.get(info.status)
        if counter:
            setattr(self, counter, getattr(self, counter) + 1)

    def mark_recovered(self, info: FileInfo) -> None:
        """복구가 성공한 파일의 상태를 '복구 완료'로 바꾸고 집계도 맞춰 조정한다."""
        old_counter = _COUNTER_BY_STATUS.get(info.status)
        if old_counter and old_counter != "recovered":
            setattr(self, old_counter, max(0, getattr(self, old_counter) - 1))
        info.status = FileStatus.RECOVERED
        self.recovered += 1

    def recoverable_files(self) -> list[FileInfo]:
        """복구 가능/부분 복구 가능한 파일만 반환 (PRD '복구 가능한 파일 보기')"""
        return [
            f
            for f in self.files
            if f.status in (FileStatus.MISMATCH, FileStatus.PARTIAL_CORRUPTION)
        ]

    def by_status(self, status: FileStatus) -> list[FileInfo]:
        return [f for f in self.files if f.status == status]

    def remove(self, info: FileInfo) -> None:
        """파일 하나를 결과에서 완전히 뺀다(Phase 2 중복 정리로 임시 휴지통에
        옮겼을 때 사용). 이걸 안 하면 content_hash는 그대로 남아있어서, 옮긴
        파일을 다시 검사한 적도 없는데 duplicate_groups()가 계속 같은 그룹을
        보여준다 — 원본은 항상 보존되니 이건 '검사 결과 목록'에서만 지우는
        것이지 실제 파일 삭제가 아니다."""
        try:
            self.files.remove(info)
        except ValueError:
            return
        self.total = max(0, self.total - 1)
        counter = _COUNTER_BY_STATUS.get(info.status)
        if counter:
            setattr(self, counter, max(0, getattr(self, counter) - 1))

    def duplicate_groups(self) -> list[list[FileInfo]]:
        """content_hash가 같은 파일들을 그룹으로 묶어 반환한다(Phase 2 '정확 중복'
        탐지). 파일이 2개 이상 모인 그룹만 반환 — 혼자인 해시는 중복이 아니므로
        제외."""
        groups: dict[str, list[FileInfo]] = {}
        for f in self.files:
            if f.content_hash:
                groups.setdefault(f.content_hash, []).append(f)
        return [group for group in groups.values() if len(group) > 1]

    def similar_groups(self, threshold: int = 10) -> list[list[FileInfo]]:
        """완전 중복(duplicate_groups)이 아닌 파일들 중에서, (1) 이미지 지문
        (perceptual_hash)이 서로 비슷하거나 (2) 파일명이 복사 접미사만 다른
        같은 폴더 안 파일과 짝을 이루면 하나의 그룹으로 묶는다(Phase 2 '유사
        중복' 탐지, 뷰어 전용 — 실제 파일은 안 건드림). threshold는 지문 값의
        해밍 거리 허용치(작을수록 엄격) — 두 신호 중 하나라도 걸리면 묶이므로
        (합집합-찾기), 한 그룹 안에 여러 쌍이 서로 다른 이유로 연결돼 있을 수
        있다."""
        exact_dup_paths = {f.path for group in self.duplicate_groups() for f in group}
        candidates = [f for f in self.files if f.path not in exact_dup_paths]
        n = len(candidates)
        if n < 2:
            return []

        index_of = {f.path: i for i, f in enumerate(candidates)}
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # 신호 1: 파일명 패턴 — 접미사를 뗀 이름이 같은 폴더의 실제 파일과 일치
        by_stripped_name: dict[tuple[str, str, str], FileInfo] = {}
        for f in candidates:
            p = Path(f.path)
            by_stripped_name[(str(p.parent), p.suffix.lower(), p.stem.lower())] = f

        for i, f in enumerate(candidates):
            p = Path(f.path)
            match = _COPY_SUFFIX_PATTERN.search(p.stem.lower())
            if not match:
                continue
            stripped = p.stem.lower()[: match.start()]
            base = by_stripped_name.get((str(p.parent), p.suffix.lower(), stripped))
            if base is not None and base.path != f.path:
                union(i, index_of[base.path])

        # 신호 2: 이미지 지문 유사도(해밍 거리) — 파일 수가 많으면 쌍 비교 비용이
        # 커지지만(N^2), 백그라운드 스레드에서 돌리는 걸 전제로 한다
        # (gui/similar_screen.py 참고).
        hashed = [(i, int(f.perceptual_hash, 16)) for i, f in enumerate(candidates) if f.perceptual_hash]
        for a in range(len(hashed)):
            i, hash_i = hashed[a]
            for b in range(a + 1, len(hashed)):
                j, hash_j = hashed[b]
                if bin(hash_i ^ hash_j).count("1") <= threshold:
                    union(i, j)

        clusters: dict[int, list[FileInfo]] = {}
        for i, f in enumerate(candidates):
            clusters.setdefault(find(i), []).append(f)

        return [group for group in clusters.values() if len(group) > 1]

    def date_groups(self, granularity: str = "month") -> list[tuple[str, list[FileInfo]]]:
        """EXIF 촬영일(FileInfo.captured_at) 기준으로 묶어 반환한다(Phase 2
        '날짜별 정리', 뷰어 전용 — 실제 파일은 안 건드림). granularity="month"면
        "YYYY년 M월"(기본), "year"면 "YYYY년" 단위로 묶는다. 최신 것이 먼저
        오고, 촬영일을 모르는 파일들은 "날짜 정보 없음"으로 묶어 맨 뒤에 둔다."""
        buckets: dict[tuple[int, ...], list[FileInfo]] = {}
        no_date: list[FileInfo] = []
        for f in self.files:
            if f.captured_at is None:
                no_date.append(f)
            elif granularity == "year":
                buckets.setdefault((f.captured_at.year,), []).append(f)
            else:
                buckets.setdefault((f.captured_at.year, f.captured_at.month), []).append(f)

        if granularity == "year":
            groups = [(f"{key[0]}년", buckets[key]) for key in sorted(buckets, reverse=True)]
        else:
            groups = [(f"{key[0]}년 {key[1]}월", buckets[key]) for key in sorted(buckets, reverse=True)]

        if no_date:
            groups.append(("날짜 정보 없음", no_date))
        return groups

    def city_groups(self) -> list[tuple[str, list[FileInfo]]]:
        """GPS 위경도(FileInfo.latitude/longitude) 기준으로 도시별로 묶어
        반환한다(Phase 2 '도시별 정리', 뷰어 전용 — 실제 파일은 안 건드림).
        date_groups()와 같은 원칙이지만, 도시 매칭 자체가 core/geocoder.py
        호출(reverse_geocoder)이 필요해서 매번 계산한다 — GPS 없는 파일은
        "위치 정보 없음"으로 묶어 맨 뒤에 둔다."""
        from core.geocoder import resolve_cities

        with_gps = [f for f in self.files if f.latitude is not None and f.longitude is not None]
        no_gps = [f for f in self.files if f.latitude is None or f.longitude is None]

        cities = resolve_cities([(f.latitude, f.longitude) for f in with_gps])

        buckets: dict[str, list[FileInfo]] = {}
        for info, city in zip(with_gps, cities):
            buckets.setdefault(city, []).append(info)

        groups = [(city, files) for city, files in sorted(buckets.items(), key=lambda kv: -len(kv[1]))]
        if no_gps:
            groups.append(("위치 정보 없음", no_gps))
        return groups

    def merge(self, other: "ScanResult") -> "ScanResult":
        """이어서 검사한 결과(other)를 이 결과 뒤에 합친 새 ScanResult를 반환한다."""
        return ScanResult(
            total=self.total + other.total,
            normal=self.normal + other.normal,
            mismatch=self.mismatch + other.mismatch,
            partial_corruption=self.partial_corruption + other.partial_corruption,
            corrupted=self.corrupted + other.corrupted,
            unsupported=self.unsupported + other.unsupported,
            not_an_image=self.not_an_image + other.not_an_image,
            recovered=self.recovered + other.recovered,
            files=list(self.files) + list(other.files),
        )
