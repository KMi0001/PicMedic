"""
core/location_inference.py 테스트

PHASE2_사진정리_기획.md "위치 정보 추론(GPS 없는 사진 보완)" — 시간 기반
보간과 유사 사진 클러스터 전파 두 경로를 각각 확인한다.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from core.location_inference import CLUSTER_LABEL, TIME_INTERP_LABEL, infer_missing_locations
from models.file_info import FileInfo


def _info(name: str, captured_at=None, lat=None, lon=None, phash=None) -> FileInfo:
    return FileInfo(
        path=f"C:/fake/{name}",
        filename=name,
        extension=".jpg",
        captured_at=captured_at,
        latitude=lat,
        longitude=lon,
        perceptual_hash=phash,
    )


def test_location_inference():
    t0 = datetime(2026, 1, 1, 12, 0, 0)

    # 1) 앞뒤 GPS 사이 - 시간 비율로 선형 보간
    before = _info("before.jpg", captured_at=t0, lat=37.0, lon=127.0)
    middle = _info("middle.jpg", captured_at=t0 + timedelta(hours=1))  # 정확히 중간 시각
    after = _info("after.jpg", captured_at=t0 + timedelta(hours=2), lat=39.0, lon=129.0)
    result = infer_missing_locations([before, middle, after], similar_groups=[])
    check("중간 시각 사진이 보간됨", middle.path in result)
    lat, lon, label = result[middle.path]
    check("보간 위도가 앞뒤 중간값(38.0)", abs(lat - 38.0) < 1e-6, lat)
    check("보간 경도가 앞뒤 중간값(128.0)", abs(lon - 128.0) < 1e-6, lon)
    check("보간 라벨이 '시간 보간'", label == TIME_INTERP_LABEL)

    # 2) 한쪽만 범위 안 - 가까운 쪽 위치를 그대로 사용
    near_before = _info("near_before.jpg", captured_at=t0 + timedelta(hours=0.5), lat=None, lon=None)
    far_gps = _info("far_gps.jpg", captured_at=t0 + timedelta(hours=100), lat=1.0, lon=1.0)
    result2 = infer_missing_locations([before, far_gps, near_before], similar_groups=[])
    check(
        "가까운 GPS(1시간 이내)만 있으면 그 위치를 그대로 씀",
        result2.get(near_before.path) == (37.0, 127.0, TIME_INTERP_LABEL),
        result2.get(near_before.path),
    )

    # 3) 앞뒤 다 max_gap_hours(기본 24h) 밖 - 추정 안 함
    isolated = _info("isolated.jpg", captured_at=t0 + timedelta(hours=50))
    gps_far1 = _info("gps_far1.jpg", captured_at=t0, lat=10.0, lon=10.0)
    gps_far2 = _info("gps_far2.jpg", captured_at=t0 + timedelta(hours=100), lat=20.0, lon=20.0)
    result3 = infer_missing_locations([gps_far1, gps_far2, isolated], similar_groups=[])
    check("양쪽 다 24시간 넘게 떨어지면 추정 안 함", isolated.path not in result3)

    # 4) 유사 사진 클러스터 전파 — 시간 정보가 없어도 클러스터 안에 GPS가 있으면 전파
    no_time_no_gps = _info("cluster_member.jpg")
    gps_member = _info("cluster_gps.jpg", lat=5.0, lon=6.0)
    cluster = [gps_member, no_time_no_gps]
    result4 = infer_missing_locations([gps_member, no_time_no_gps], similar_groups=[cluster])
    check(
        "클러스터 동료의 GPS가 전파됨",
        result4.get(no_time_no_gps.path) == (5.0, 6.0, CLUSTER_LABEL),
        result4.get(no_time_no_gps.path),
    )

    # 5) 시간 보간으로 이미 채워진 파일은 클러스터가 덮어쓰지 않음(1번 우선)
    cluster_with_middle = [after, middle]  # middle은 위 1번에서 이미 채워짐
    result5 = infer_missing_locations([before, middle, after], similar_groups=[cluster_with_middle])
    check("시간 보간 결과가 클러스터 전파로 덮어써지지 않음", result5[middle.path][2] == TIME_INTERP_LABEL)

    # 6) GPS 있는 파일 자신은 결과에 없음
    check("GPS 있는 파일은 추정 대상이 아님", before.path not in result)
