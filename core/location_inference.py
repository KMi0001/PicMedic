"""
core/location_inference.py

GPS가 없는 사진의 위치를 두 가지 순수 로직으로 추정한다(Phase 2 "위치 정보
추론(GPS 없는 사진 보완)" — PHASE2_사진정리_기획.md 참고). AI/ML 불필요 —
정렬·시간차 계산·이미 계산된 유사 사진 클러스터 재사용만으로 충분하다.

1. 시간 기반 보간: 같은 스캔 안에서 GPS 있는 사진들을 촬영 시각순으로 정렬해두고,
   GPS 없는 사진은 시간상 가장 가까운 GPS 사진의 위치를 가져다 쓰거나(앞뒤
   양쪽에 GPS 사진이 있으면 시간 비율로 선형 보간). 간격이 max_gap_hours를
   넘으면 그 방향은 포기한다 — 비행기 이동 등으로 완전히 틀린 위치가 나오는
   것을 막기 위한 상한.
2. 유사 사진 클러스터 기반 전파: ScanResult.similar_groups()가 이미 계산해둔
   퍼셉추얼 해시 클러스터를 재사용 — 같은 클러스터 안에 GPS 있는 사진이
   하나라도 있으면(첫 번째로 찾은 것) 그 위치를 클러스터 전체에 적용한다.
   위 1번으로 이미 채워진 파일은 건너뛴다.

결과는 FileInfo.latitude/longitude(실측 전용)에 절대 쓰지 않는다 — 호출부가
FileInfo.inferred_latitude/longitude + location_inferred_from에만 채워서,
추정 위치가 실측 데이터처럼 보이지 않도록 항상 구분한다.
"""

from __future__ import annotations

import bisect
from datetime import timedelta

from models.file_info import FileInfo

TIME_INTERP_LABEL = "시간 보간"
CLUSTER_LABEL = "유사 사진"


def infer_missing_locations(
    files: list[FileInfo],
    similar_groups: list[list[FileInfo]],
    max_gap_hours: float = 24.0,
) -> dict[str, tuple[float, float, str]]:
    """실측 GPS가 없는 파일들에 대해 path -> (위도, 경도, 추정 방법 라벨)
    딕셔너리를 반환한다. 실측 GPS가 있는 파일이나, 두 방법 다 실패한 파일은
    결과에 포함되지 않는다."""
    gps_files = [f for f in files if f.latitude is not None and f.longitude is not None]
    no_gps_files = [f for f in files if f.latitude is None or f.longitude is None]
    inferred: dict[str, tuple[float, float, str]] = {}
    if not gps_files or not no_gps_files:
        return inferred

    # 1) 시간 기반 보간 — captured_at이 있는 GPS 사진만 시간순으로 정렬해두고
    # bisect로 가장 가까운 앞/뒤 GPS 사진을 O(log n)에 찾는다.
    timed_gps = sorted((f for f in gps_files if f.captured_at is not None), key=lambda f: f.captured_at)
    times = [f.captured_at for f in timed_gps]
    max_gap = timedelta(hours=max_gap_hours)

    for f in no_gps_files:
        if f.captured_at is None or not timed_gps:
            continue
        idx = bisect.bisect_right(times, f.captured_at)
        before = timed_gps[idx - 1] if idx > 0 else None
        after = timed_gps[idx] if idx < len(timed_gps) else None
        before_ok = before is not None and (f.captured_at - before.captured_at) <= max_gap
        after_ok = after is not None and (after.captured_at - f.captured_at) <= max_gap

        if before_ok and after_ok:
            total = (after.captured_at - before.captured_at).total_seconds()
            frac = (f.captured_at - before.captured_at).total_seconds() / total if total else 0.0
            lat = before.latitude + (after.latitude - before.latitude) * frac
            lon = before.longitude + (after.longitude - before.longitude) * frac
            inferred[f.path] = (lat, lon, TIME_INTERP_LABEL)
        elif before_ok:
            inferred[f.path] = (before.latitude, before.longitude, TIME_INTERP_LABEL)
        elif after_ok:
            inferred[f.path] = (after.latitude, after.longitude, TIME_INTERP_LABEL)

    # 2) 유사 사진 클러스터 전파 — 위에서 못 채운 파일만 대상
    gps_by_path = {f.path: (f.latitude, f.longitude) for f in gps_files}
    for cluster in similar_groups:
        cluster_gps = next((gps_by_path[f.path] for f in cluster if f.path in gps_by_path), None)
        if cluster_gps is None:
            continue
        for f in cluster:
            if f.path in gps_by_path or f.path in inferred:
                continue
            inferred[f.path] = (cluster_gps[0], cluster_gps[1], CLUSTER_LABEL)

    return inferred
