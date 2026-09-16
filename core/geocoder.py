"""
core/geocoder.py

"도시별 정리"용 위경도 -> 도시명 매칭. GeoNames(CC-BY 4.0) 파생 도시 좌표
데이터(assets/geonames_cities1000.csv)를 scipy(BSD)의 cKDTree로 직접
최근접 탐색한다.

개인정보 원칙: 위경도/도시명은 이 프로세스 밖으로 절대 나가지 않는다. 어떤
네트워크 요청도 하지 않으며, 이 프로세스 안에 들어있는 CSV만 참조한다
(experiments/city_organize_prototype에서 확인).

2026-09-11, reverse_geocoder 패키지(LGPL)를 걷어내고 자체 구현으로 교체 —
RESTORATION_QUALITY_PLAN.md 5-3에서 상업 배포 시 LGPL의 재연결/교체 가능성
요건이 PyInstaller 정적 번들링과 어떻게 맞물리는지 법률 검토가 필요하다는
문제가 나와서, 법률 검토 대신 더 간단한 해결책(라이브러리 자체를 안 씀)을
택했다. reverse_geocoder 패키지의 실제 코드(__init__.py + cKDTree_MP.py)는
15KB 남짓의 얇은 KD-tree 래퍼였고, core/geocoder.py는 이미 한국 지역 보정
(_get_kr_only_index)에서 같은 패턴(cKDTree 직접 사용)을 쓰고 있었다 — 그
패턴을 전세계로 넓힌 것뿐이라 이 파일 입장에서 낯선 접근이 아니다.
experiments/geocoder_license_prototype/compare.py로 기존 reverse_geocoder
결과와 8/8 좌표 완전 일치 검증 후 교체(백령도 국경 오탐 케이스 포함 — 아래
_get_kr_only_index가 그 오탐을 고치는 방식은 그대로 유지).
데이터 자체(GeoNames)는 CC-BY 4.0이라 코드 라이선스와 무관하고, 저작자 표시는
THIRD_PARTY_NOTICES.txt에 남긴다.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CSV_PATH = _PROJECT_ROOT / "assets" / "geonames_cities1000.csv"

# 로마자 표기만 준다(한국어 이름 필드 없음 — CSV 직접 확인). 국내 사진이
# 대부분일 것으로 보고 주요 도시 위주로만 번역하고, 목록에 없으면 원래 로마자
# 표기를 그대로 보여준다("완벽한 번역"이 아니라 "실사용에 흔한 것만" 원칙 —
# core/photo_category.py의 카테고리 프롬프트와 같은 접근). 표기는
# assets/geonames_cities1000.csv 'name' 컬럼 원문과 정확히 일치해야 매칭된다.
_KOREAN_CITY_NAMES: dict[str, str] = {
    "Seoul": "서울", "Busan": "부산", "Incheon": "인천", "Daegu": "대구",
    "Daejeon": "대전", "Gwangju": "광주", "Ulsan": "울산",
    "Suwon-si": "수원", "Seongnam-si": "성남", "Goyang-si": "고양",
    "Bucheon-si": "부천", "Ansan-si": "안산", "Anyang-si": "안양",
    "Cheongju-si": "청주", "Jeonju": "전주", "Cheonan": "천안",
    "Namyangju": "남양주", "Hwaseong-si": "화성", "Pohang": "포항",
    "Uijeongbu-si": "의정부", "Kimhae": "김해", "Gumi": "구미",
    "Icheon-si": "이천", "Jeju-si": "제주", "Seogwipo": "서귀포",
    "Yangsan": "양산", "Chuncheon": "춘천", "Suncheon": "순천",
    "Moppo": "목포", "Yeosu": "여수", "Kang-neung": "강릉",
    "Chinju": "진주", "Sokcho": "속초", "Kyonju": "경주",
    "Andong": "안동", "Osan": "오산", "Wonju": "원주",
    "Kwangyang": "광양", "Kunsan": "군산", "Iksan": "익산",
    "Asan": "아산", "Gongju": "공주", "Nonsan": "논산",
    "Naju": "나주", "Gimcheon": "김천", "Sangju": "상주",
    "Miryang": "밀양", "Changwon": "창원", "Paju": "파주",
    "Yangju": "양주", "Guri-si": "구리", "Hanam": "하남",
    "Gapyeong": "가평", "Goseong": "고성",
}

# 국내 다음으로 흔할 해외 여행지 위주 — 마찬가지로 목록에 없으면 원문 표기.
_INTL_CITY_NAMES: dict[str, str] = {
    "Tokyo": "도쿄", "Osaka": "오사카", "Kyoto": "교토", "Fukuoka": "후쿠오카",
    "Sapporo": "삿포로", "Nagoya": "나고야", "Yokohama": "요코하마", "Naha": "나하",
    "Beijing": "베이징", "Shanghai": "상하이", "Guangzhou": "광저우",
    "Hong Kong": "홍콩", "Macau": "마카오", "Taipei": "타이베이", "Kaohsiung": "가오슝",
    "Bangkok": "방콕", "Chiang Mai": "치앙마이", "Phuket": "푸켓", "Pattaya City": "파타야",
    "Singapore": "싱가포르", "Kuala Lumpur": "쿠알라룸푸르", "Denpasar": "덴파사르",
    "Jakarta": "자카르타", "Hanoi": "하노이", "Ho Chi Minh City": "호찌민",
    "Da Nang": "다낭", "Nha Trang": "나트랑", "Manila": "마닐라", "Cebu City": "세부",
    "New York City": "뉴욕", "Los Angeles": "로스앤젤레스", "San Francisco": "샌프란시스코",
    "Las Vegas": "라스베이거스", "Honolulu": "호놀룰루", "Hagatna Village": "괌",
    "Toronto": "토론토", "Vancouver": "밴쿠버",
    "London": "런던", "Paris": "파리", "Rome": "로마", "Barcelona": "바르셀로나",
    "Madrid": "마드리드", "Amsterdam": "암스테르담", "Prague": "프라하",
    "Vienna": "빈", "Berlin": "베를린", "Munich": "뮌헨", "Zurich": "취리히",
    "Istanbul": "이스탄불", "Dubai": "두바이",
    "Sydney": "시드니", "Melbourne": "멜버른", "Auckland": "오클랜드",
}

# 한국 시/도(광역시·특별시 포함, GeoNames admin1 컬럼 기준) 한국어 이름 —
# 도시별 정리 지도에서 한 나라 안에 도시가 너무 많이 보일 때 한 단계 더
# 뭉쳐 보여주는 "시/도 단위"용(2026-09-17). 해외는 이 파일의 기존 원칙대로
# 흔한 지명만 챙기지 않고 GeoNames admin1 원문을 그대로 보여준다(국내 사진이
# 대부분일 거란 전제 — resolve_province_names 참고).
_KOREAN_PROVINCE_NAMES: dict[str, str] = {
    "Seoul": "서울", "Busan": "부산", "Daegu": "대구", "Incheon": "인천",
    "Daejeon": "대전", "Gwangju": "광주", "Ulsan": "울산",
    "Gyeonggi-do": "경기도", "Gangwon-do": "강원도",
    "Chungcheongbuk-do": "충청북도", "Chungcheongnam-do": "충청남도",
    "Jeollabuk-do": "전라북도", "Jeollanam-do": "전라남도",
    "Gyeongsangbuk-do": "경상북도", "Gyeongsangnam-do": "경상남도",
    "Jeju-do": "제주도",
}

_KOREAN_COUNTRY_NAMES: dict[str, str] = {
    "KR": "대한민국", "JP": "일본", "CN": "중국", "HK": "홍콩", "MO": "마카오",
    "TW": "대만", "TH": "태국", "SG": "싱가포르", "MY": "말레이시아",
    "ID": "인도네시아", "VN": "베트남", "PH": "필리핀", "US": "미국", "CA": "캐나다",
    "GB": "영국", "FR": "프랑스", "IT": "이탈리아", "ES": "스페인", "NL": "네덜란드",
    "CZ": "체코", "AT": "오스트리아", "DE": "독일", "CH": "스위스", "TR": "튀르키예",
    "AE": "아랍에미리트", "AU": "호주", "NZ": "뉴질랜드", "GU": "괌",
}


def _localize(name: str, cc: str) -> str:
    """(도시 로마자 표기, 국가 코드) -> 화면에 보여줄 한국어 라벨. 국내는
    도시명만(국가 표기가 중복 정보라 생략), 해외는 "도시, 국가" 형태 —
    둘 다 매핑에 없는 이름은 원래 로마자 표기를 그대로 보여준다."""
    if cc == "KR":
        return _KOREAN_CITY_NAMES.get(name, name)

    city = _INTL_CITY_NAMES.get(name, name)
    country = _KOREAN_COUNTRY_NAMES.get(cc, cc)
    return f"{city}, {country}"


# 대한민국 대략적인 경계 상자(제주/백령도/독도까지 여유 있게 포함) — 이
# 안의 좌표는 반드시 한국 도시로만 매칭시키기 위한 기준(_in_korea_bbox 참고).
_KR_LAT_RANGE = (32.5, 39.0)
_KR_LON_RANGE = (124.0, 132.0)

# 전세계 도시 KD-tree(_get_global_index) / 한국 도시만 담은 KD-tree
# (_get_kr_only_index) — 둘 다 처음 쓸 때 한 번만 만들어서 재사용.
_global_index: Optional[tuple] = None
_kr_only_index: Optional[tuple] = None


def _in_korea_bbox(lat: float, lon: float) -> bool:
    return _KR_LAT_RANGE[0] <= lat <= _KR_LAT_RANGE[1] and _KR_LON_RANGE[0] <= lon <= _KR_LON_RANGE[1]


def _get_global_index():
    """assets/geonames_cities1000.csv 전체를 읽어 KD-tree를 한 번만 만들고
    캐싱한다(모듈 전역, 프로세스 수명 동안 재사용 — 7.8MB CSV를 매번 다시
    읽지 않는다). resolve_cities()와 _get_kr_only_index() 둘 다 여기서
    로드한 locations를 공유해서 CSV를 두 번 읽지 않는다."""
    global _global_index
    if _global_index is not None:
        return _global_index

    from scipy.spatial import cKDTree

    with open(_CSV_PATH, encoding="utf-8") as f:
        locations = list(csv.DictReader(f))
    coords = [(float(loc["lat"]), float(loc["lon"])) for loc in locations]
    tree = cKDTree(coords)
    _global_index = (tree, locations)
    return _global_index


def _get_kr_only_index():
    """assets/geonames_cities1000.csv는 전세계 도시를 국경 구분 없이 순수
    최근접(직선거리)으로만 찾는다 — 그래서 한국 서해안·도서 지역처럼 국내
    도시 데이터가 듬성듬성한 지점은 바다 건너 중국/북한 도시가 기하학적으로
    더 가깝다고 잘못 판단할 수 있다(2026-09-10, 사용자 리포트 — 백령도 좌표를
    넣으면 북한 도시로 매칭되는 걸로 재현 확인. 서해안 전반에서 같은 방식으로
    중국 도시가 나올 수 있음).

    고치는 방법: 좌표가 한국 영역 안(_in_korea_bbox)인데 결과가 다른 나라로
    나오면, 한국 도시만 모아 만든 이 인덱스에서 다시 찾아 그 결과로 바꾼다.
    _get_global_index()가 이미 읽어둔 locations를 그대로 재사용하므로 CSV를
    다시 읽지 않는다."""
    global _kr_only_index
    if _kr_only_index is not None:
        return _kr_only_index

    from scipy.spatial import cKDTree

    _, all_locations = _get_global_index()
    kr_locations = [loc for loc in all_locations if loc["cc"] == "KR"]
    coords = [(float(loc["lat"]), float(loc["lon"])) for loc in kr_locations]
    tree = cKDTree(coords)
    _kr_only_index = (tree, kr_locations)
    return _kr_only_index


def _nearest_kr_city(lat: float, lon: float) -> dict:
    tree, kr_locations = _get_kr_only_index()
    _, idx = tree.query((lat, lon), k=1)
    return kr_locations[idx]


def _resolve_raw(coords: list[tuple[float, float]]) -> list[dict]:
    """coords 각각에 가장 가까운 GeoNames 도시 레코드(name/cc 등 원본 dict)를
    찾는다. resolve_cities()·resolve_country_codes() 둘 다 같은 최근접 탐색
    결과(한국 보정 포함)를 공유하도록 여기로 뽑아냈다."""
    if not coords:
        return []

    tree, all_locations = _get_global_index()
    _, idxs = tree.query(coords)
    results = [all_locations[i] for i in idxs]

    # 한국 영역 안 좌표인데 다른 나라로 매칭됐으면(_get_kr_only_index 참고)
    # 한국 도시로만 다시 찾는다 — 국내 사진이 대부분일 거란 core/geocoder.py
    # 전반의 전제와 같은 이유로, 해외는 이 보정을 하지 않는다(다른 나라의
    # 국경 오탐까지 다 고치려면 나라마다 같은 보정이 필요한데 실사용 빈도가
    # 훨씬 낮음).
    for i, (lat, lon) in enumerate(coords):
        if results[i]["cc"] != "KR" and _in_korea_bbox(lat, lon):
            results[i] = _nearest_kr_city(lat, lon)

    return results


def resolve_cities(coords: list[tuple[float, float]]) -> list[Optional[str]]:
    """coords(위도, 경도) 목록을 한 번에 한국어 도시 라벨로 매칭한다(주요
    도시만 번역, 나머지는 로마자 표기 — _localize 참고). 빈 목록이면 빈
    목록. 개별 좌표가 이상해도(예: 범위 밖) 항상 가장 가까운 지점을 찾아
    결과를 반환하므로 None은 나오지 않지만, 시그니처는 향후 실패 케이스를
    대비해 Optional로 둔다."""
    return [_localize(r["name"], r["cc"]) for r in _resolve_raw(coords)]


def resolve_country_codes(coords: list[tuple[float, float]]) -> list[str]:
    """coords 각각이 속한 나라의 ISO 2자리 코드(예: "KR")를 반환한다 —
    도시별 정리 지도가 화면에 나라가 여러 개 보일 때 도시 단위 대신 나라
    단위로 뭉쳐 보여주기 위해 씀(2026-09-17, 사용자 요청: "국가가 2개 이상일
    경우엔 나라 이름만"). resolve_cities()와 같은 최근접 탐색 결과를 쓰므로
    같은 좌표에 대해 두 함수가 항상 같은 나라로 일치한다."""
    return [r["cc"] for r in _resolve_raw(coords)]


def country_name_ko(cc: str) -> str:
    """나라 코드 -> 한국어 나라 이름(_KOREAN_COUNTRY_NAMES에 없으면 코드
    그대로). gui/city_map_view.py가 나라 단위로 뭉친 마커의 라벨에 쓴다."""
    return _KOREAN_COUNTRY_NAMES.get(cc, cc)


def resolve_province_names(coords: list[tuple[float, float]]) -> list[str]:
    """coords 각각이 속한 시/도 단위(GeoNames admin1) 라벨. 도시별 정리
    지도가 한 나라 안에 도시 마커가 너무 많이 보일 때(예: 국내 사진만
    수만 장) 시/도 단위로 한 단계 더 뭉쳐 보여주는 데 씀(2026-09-17, 사용자
    요청 — "확대/축소 할때마다 시/도 표기를 좀 넓게"). admin1 정보가 없는
    드문 경우엔 도시 라벨로 대신한다(빈 라벨보다 낫다)."""
    result = []
    for r in _resolve_raw(coords):
        admin1 = r.get("admin1") or ""
        if not admin1:
            result.append(_localize(r["name"], r["cc"]))
            continue
        result.append(_KOREAN_PROVINCE_NAMES.get(admin1, admin1))
    return result
