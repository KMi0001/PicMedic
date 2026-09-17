"""
utils/topojson.py 테스트

2026-09-18 사용자 요청: "도 단위로는 얇은 선이라도 나뉘어 있음 좋을거
같아서" — assets/kr_provinces_10m.json(Natural Earth 1:10m Admin-1
States/Provinces, naturalearthdata.com 공식 배포, 퍼블릭 도메인에서
대한민국 17개 시/도만 추출)을 load_country_polygons과 같은 최소 디코더
(scale=[1,1]/translate=[0,0]로 quantization 없이 델타=원본 좌표 차이가
되게 만들어 기존 파서를 그대로 재사용)로 읽는 load_province_polygons를
추가했다 — 이 테스트가 그 결과를 고정한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from utils.assets import asset_path
from utils.topojson import load_province_polygons


def test_kr_provinces_topojson_loads_all_17():
    provinces = load_province_polygons(asset_path("kr_provinces_10m.json"))
    check("대한민국 시/도 17개가 모두 로드됨", len(provinces) == 17, len(provinces))

    names_ko = {name_ko for _name, name_ko, _rings in provinces}
    check(
        "주요 시/도 한국어 이름이 정확히 들어있음",
        {"서울특별시", "부산광역시", "제주특별자치도", "경기도"} <= names_ko,
        names_ko,
    )

    for name, name_ko, rings in provinces:
        check(f"{name_ko or name}에 폴리곤 링이 최소 1개 있음", len(rings) >= 1, (name, len(rings)))
        for ring in rings:
            check(
                f"{name_ko or name}의 링 하나가 폴리곤을 이룰 만큼 점이 있음(3개 이상)",
                len(ring) >= 3,
                (name, len(ring)),
            )


def test_kr_provinces_coordinates_are_within_korea_bounds():
    """디코딩이 잘못되면(예: scale/translate 부호나 delta 누적 실수) 좌표가
    한국 근처가 아닌 엉뚱한 곳(원점 근처, 태평양 등)에 찍힌다 — 대략적인
    위경도 범위로 회귀를 막는다."""
    provinces = load_province_polygons(asset_path("kr_provinces_10m.json"))
    all_points = [pt for _name, _name_ko, rings in provinces for ring in rings for pt in ring]
    check("좌표가 있음", len(all_points) > 1000, len(all_points))

    lons = [lon for lon, lat in all_points]
    lats = [lat for lon, lat in all_points]
    check(
        f"경도가 대한민국 범위 안(124~132)에 있음(실측 {min(lons):.2f}~{max(lons):.2f})",
        124 <= min(lons) and max(lons) <= 132,
    )
    check(
        f"위도가 대한민국 범위 안(32~39)에 있음(실측 {min(lats):.2f}~{max(lats):.2f})",
        32 <= min(lats) and max(lats) <= 39,
    )


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_kr_provinces_topojson_loads_all_17()
    test_kr_provinces_coordinates_are_within_korea_bounds()
    print("OK")
