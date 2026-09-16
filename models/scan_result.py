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

    def similar_groups(self, threshold: int = 8) -> list[list[FileInfo]]:
        """완전 중복(duplicate_groups)이 아닌 파일들 중에서, (1) 이미지 지문
        (perceptual_hash)이 서로 비슷하거나 (2) 파일명이 복사 접미사만 다른
        같은 폴더 안 파일과 짝을 이루면 하나의 그룹으로 묶는다(Phase 2 '유사
        중복' 탐지, 뷰어 전용 — 실제 파일은 안 건드림). threshold는 지문 값의
        해밍 거리 허용치(작을수록 엄격).

        신호 2(지문 유사도)는 "대표 해시" 방식으로 묶는다 — 그룹에 처음 들어온
        사진의 해시를 그 그룹의 대표로 고정하고, 새 후보는 대표하고만 비교한다
        (그룹 내 다른 멤버끼리는 서로 비교 안 함). 예전에는 아무 쌍이나
        threshold 이내면 이어 붙이는 union-find라서 A-B, B-C가 각각 걸리면
        A-C가 threshold를 훨씬 넘어도 한 그룹으로 묶이는 "연쇄 효과"가 있었다
        (2026-09-12, 사용자가 "유사 사진으로 묶었는데 눈으로 봐도 너무 다르다"고
        제보). 대표 방식은 그룹 안 임의의 두 사진 사이 거리를 항상
        2*threshold 이내로 보장한다(삼각부등식: dist(i,j) <= dist(i,대표) +
        dist(대표,j)). 부수 효과로 비교 횟수도 "사진 수 x 사진 수"에서
        "사진 수 x 지금까지 만들어진 그룹 수"로 줄어든다 — 비슷한 사진(버스트샷
        등)이 많을수록 그룹 수가 적어서 훨씬 빨라진다(3만~4만 장 스캔에서
        오래 걸린다는 제보로 같이 개선)."""
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

        # 신호 2: 이미지 지문 유사도(해밍 거리) — 대표 해시 방식(위 docstring 참고).
        # representatives에는 그룹당 대표 1개(그 그룹에 처음 들어온 사진)의
        # (인덱스, 해시)만 쌓인다. 새 후보는 이 대표들하고만 비교하고, 걸리면
        # 첫 번째로 맞는 대표에 합류한 뒤 나머지 대표는 더 보지 않는다.
        representatives: list[tuple[int, int]] = []
        for i, f in enumerate(candidates):
            if not f.perceptual_hash:
                continue
            hash_i = int(f.perceptual_hash, 16)
            for rep_index, rep_hash in representatives:
                if bin(hash_i ^ rep_hash).count("1") <= threshold:
                    union(i, rep_index)
                    break
            else:
                representatives.append((i, hash_i))

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
        """GPS 위경도(FileInfo.latitude/longitude, 없으면 추정 위치) 기준으로
        도시별로 묶어 반환한다(Phase 2 '도시별 정리', 뷰어 전용 — 실제 파일은
        안 건드림). date_groups()와 같은 원칙이지만, 도시 매칭 자체가
        core/geocoder.py 호출(reverse_geocoder)이 필요해서 매번 계산한다.

        실측 GPS가 없는 파일은 core/location_inference.py로 위치 추정을 먼저
        시도한다(시간 보간 + 유사 사진 클러스터 전파) — 추정도 안 되는 파일만
        "위치 정보 없음"으로 묶어 맨 뒤에 둔다. 추정된 파일은 FileInfo.
        location_inferred_from에 방법이 남으므로, 화면에서 실측과 구분해서
        보여줄 수 있다."""
        from core.geocoder import resolve_cities
        from core.location_inference import infer_missing_locations

        with_gps = [f for f in self.files if f.latitude is not None and f.longitude is not None]
        no_gps = [f for f in self.files if f.latitude is None or f.longitude is None]

        inferred = infer_missing_locations(self.files, self.similar_groups())
        for f in no_gps:
            entry = inferred.get(f.path)
            if entry is not None:
                f.inferred_latitude, f.inferred_longitude, f.location_inferred_from = entry
            else:
                f.inferred_latitude = f.inferred_longitude = f.location_inferred_from = None

        located = with_gps + [f for f in no_gps if f.path in inferred]
        still_no_location = [f for f in no_gps if f.path not in inferred]

        coords = [f.effective_location() for f in located]
        cities = resolve_cities(coords)

        buckets: dict[str, list[FileInfo]] = {}
        for info, city in zip(located, cities):
            buckets.setdefault(city, []).append(info)

        groups = [(city, files) for city, files in sorted(buckets.items(), key=lambda kv: -len(kv[1]))]
        if still_no_location:
            groups.append(("위치 정보 없음", still_no_location))
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
