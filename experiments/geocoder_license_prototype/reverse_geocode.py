"""
experiments/geocoder_license_prototype/reverse_geocode.py

RESTORATION_QUALITY_PLAN.md 5-3에서 발견된 문제(reverse_geocoder 패키지가
LGPL)를 해결하기 위한 프로토타입 — reverse_geocoder 패키지(LGPL, __init__.py +
cKDTree_MP.py 합쳐 15KB 남짓의 얇은 래퍼)를 걷어내고, 그 패키지가 쓰는 것과
같은 GeoNames 파생 데이터(rg_cities1000.csv, CC-BY 4.0 — 코드가 아니라 데이터라
LGPL과 무관)를 우리 코드로 직접 읽어 scipy(BSD)의 cKDTree로 최근접 탐색한다.

core/geocoder.py는 이미 한국 지역 보정(_get_kr_only_index)에서 이 패턴을 똑같이
쓰고 있었다 — reverse_geocoder.RGeocoder가 로드해둔 locations를 가져다 자체
cKDTree를 만드는 방식. 이 프로토타입은 그 패턴을 "한국만"이 아니라 전세계로
확장한 것뿐이라, core/geocoder.py 입장에서 낯선 접근이 아니다.

검증: 같은 CSV로 reverse_geocoder.search()와 이 모듈의 search()가 동일한 좌표에
대해 같은 결과를 내는지 compare.py로 비교.
"""

from __future__ import annotations

import csv
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "rg_cities1000.csv"

_tree = None
_locations: list[dict] = []


def _load():
    global _tree, _locations
    if _tree is not None:
        return

    from scipy.spatial import cKDTree

    with open(_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _locations = list(reader)

    coords = [(float(row["lat"]), float(row["lon"])) for row in _locations]
    _tree = cKDTree(coords)


def search(coords: list[tuple[float, float]]) -> list[dict]:
    """reverse_geocoder.search()와 같은 반환 형식(dict 목록: name/cc/lat/lon/
    admin1/admin2)의 최근접 도시 목록."""
    _load()
    if not coords:
        return []
    _, idxs = _tree.query(coords)
    # scipy는 좌표 1개면 스칼라를, 여러 개면 배열을 돌려준다 — 항상 리스트로 맞춘다.
    try:
        idxs = list(idxs)
    except TypeError:
        idxs = [idxs]
    return [_locations[i] for i in idxs]
