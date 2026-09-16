"""
tests/test_geocoder.py

core/geocoder.py 회귀 테스트 — 2026-09-11 reverse_geocoder(LGPL) 제거 후 처음
생기는 테스트 파일(그전까지 이 모듈은 테스트가 전혀 없었음). 최소한의 매칭
정확도(주요 도시)와, 이 모듈이 존재하는 핵심 이유인 국경 오탐 보정(백령도 —
core/geocoder.py:_get_kr_only_index)이 계속 지켜지는지를 확인한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from core.geocoder import country_name_ko, resolve_cities, resolve_country_codes


def test_geocoder():
    check("빈 목록 입력 시 빈 목록 반환", resolve_cities([]) == [])

    labels = resolve_cities([
        (37.5665, 126.9780),   # 서울
        (35.1796, 129.0756),   # 부산
        (40.7128, -74.0060),   # New York
        (48.8566, 2.3522),     # Paris
    ])
    check("서울 좌표가 '서울'로 매칭됨", labels[0] == "서울", labels[0])
    check("부산 좌표가 '부산'으로 매칭됨", labels[1] == "부산", labels[1])
    check("뉴욕 좌표가 '뉴욕, 미국'으로 매칭됨", labels[2] == "뉴욕, 미국", labels[2])
    check("파리 좌표가 '파리, 프랑스'로 매칭됨", labels[3] == "파리, 프랑스", labels[3])

    # 국경 오탐 보정 회귀 테스트 — 백령도 좌표를 순수 최근접으로 찾으면
    # 북한 도시(cc='KP')가 나온다(2026-09-10 사용자 리포트로 발견). 한국
    # 영역 안이면 한국 도시로만 다시 찾는 보정이 계속 걸려야 한다.
    baengnyeongdo = resolve_cities([(37.9522, 124.6314)])[0]
    check(
        "백령도 좌표는 국경 오탐 보정으로 북한이 아닌 한국 도시로 매칭됨",
        baengnyeongdo is not None and "북한" not in baengnyeongdo,
        baengnyeongdo,
    )

    # 배치 조회 결과 순서가 입력 순서와 일치하는지(내부적으로 cKDTree.query를
    # 배치로 한 번에 부르므로, 순서가 섞이면 엉뚱한 사진에 엉뚱한 도시명이 붙는
    # 치명적인 버그가 된다).
    order_check = resolve_cities([
        (35.1796, 129.0756),   # 부산
        (37.5665, 126.9780),   # 서울
    ])
    check(
        "여러 좌표를 한 번에 조회해도 입력 순서와 결과 순서가 일치함",
        order_check == ["부산", "서울"],
        order_check,
    )


def test_resolve_country_codes():
    """도시별 정리 지도의 나라 단위 집계(gui/city_map_view.py, 2026-09-17)용
    — resolve_cities와 같은 좌표에 대해 항상 같은 나라로 일치해야 한다."""
    check("빈 목록 입력 시 빈 목록 반환", resolve_country_codes([]) == [])

    coords = [
        (37.5665, 126.9780),   # 서울
        (35.1796, 129.0756),   # 부산
        (35.6762, 139.6503),   # 도쿄
        (40.7128, -74.0060),   # New York
    ]
    codes = resolve_country_codes(coords)
    check("서울 -> KR", codes[0] == "KR", codes[0])
    check("부산 -> KR", codes[1] == "KR", codes[1])
    check("도쿄 -> JP", codes[2] == "JP", codes[2])
    check("뉴욕 -> US", codes[3] == "US", codes[3])

    # 백령도(국경 오탐 보정 대상)도 resolve_cities와 똑같이 KR로 나와야
    # 두 함수가 어긋나지 않는다 — 어긋나면 지도에서 도시 라벨은 "한국"인데
    # 나라 단위로 뭉칠 땐 다른 나라 마커에 섞이는 모순이 생긴다.
    baengnyeongdo_code = resolve_country_codes([(37.9522, 124.6314)])[0]
    check("백령도 나라 코드도 KR(도시명 보정과 일치)", baengnyeongdo_code == "KR", baengnyeongdo_code)

    check("국가명 한국어 변환 - KR", country_name_ko("KR") == "대한민국")
    check("국가명 한국어 변환 - JP", country_name_ko("JP") == "일본")
    check("매핑에 없는 코드는 코드 그대로 반환", country_name_ko("ZZ") == "ZZ")


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_geocoder()
    test_resolve_country_codes()
    print("OK")
