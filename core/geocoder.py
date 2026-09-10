"""
core/geocoder.py

"도시별 정리"용 위경도 -> 도시명 매칭. reverse_geocoder(오프라인, 내장 도시
좌표 CSV로 최근접 지점 탐색 — 인터넷 호출 없음)를 감싼다.

개인정보 원칙: 위경도/도시명은 이 프로세스 밖으로 절대 나가지 않는다. 어떤
네트워크 요청도 하지 않으며, reverse_geocoder 패키지 자체에 내장된 CSV만
참조한다(experiments/city_organize_prototype에서 확인).

mode=1(단일 프로세스) 고정 — reverse_geocoder 기본값(mode=2)은 내부적으로
multiprocessing.Process를 새로 띄우는데, Windows에서 PyInstaller로 패키징한
exe가 이걸 그대로 쓰면 freeze_support() 없이 자기 자신을 무한히 재실행할 수
있다(실제로 프로토타입에서 재현됨). 우리 규모(수만 장)에서는 단일 프로세스
로도 충분히 빠르다(실측: 로드 ~0.3~8초 1회 + 사진당 ~1ms)."""

from __future__ import annotations

from typing import Optional

# reverse_geocoder(GeoNames 파생 데이터)는 로마자 표기만 준다(한국어 이름
# 필드 없음 — core/geocoder.py 개발 중 CSV 직접 확인). 국내 사진이 대부분일
# 것으로 보고 주요 도시 위주로만 번역하고, 목록에 없으면 원래 로마자 표기를
# 그대로 보여준다("완벽한 번역"이 아니라 "실사용에 흔한 것만" 원칙 —
# core/photo_category.py의 카테고리 프롬프트와 같은 접근). 표기는 reverse_geocoder의
# rg_cities1000.csv 'name' 컬럼 원문과 정확히 일치해야 매칭된다.
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

# 한국 도시만 담은 KD-tree — 처음 쓸 때 한 번만 만들어서 재사용(_get_kr_only_index).
_kr_only_index: Optional[tuple] = None


def _in_korea_bbox(lat: float, lon: float) -> bool:
    return _KR_LAT_RANGE[0] <= lat <= _KR_LAT_RANGE[1] and _KR_LON_RANGE[0] <= lon <= _KR_LON_RANGE[1]


def _get_kr_only_index():
    """reverse_geocoder(rg_cities1000.csv)는 전세계 도시를 국경 구분 없이
    순수 최근접(직선거리)으로만 찾는다 — 그래서 한국 서해안·도서 지역처럼
    국내 도시 데이터가 듬성듬성한 지점은 바다 건너 중국/북한 도시가 기하
    학적으로 더 가깝다고 잘못 판단할 수 있다(2026-09-10, 사용자 리포트 —
    백령도 좌표를 넣으면 북한 도시로 매칭되는 걸로 재현 확인. 서해안 전반에서
    같은 방식으로 중국 도시가 나올 수 있음).

    고치는 방법: 좌표가 한국 영역 안(_in_korea_bbox)인데 결과가 다른 나라로
    나오면, 한국 도시만 모아 만든 이 인덱스에서 다시 찾아 그 결과로 바꾼다.
    reverse_geocoder가 이미 mode=1로 로드해둔 싱글턴(RGeocoder)의 locations를
    그대로 재사용하므로 CSV를 다시 읽지 않는다."""
    global _kr_only_index
    if _kr_only_index is not None:
        return _kr_only_index

    import reverse_geocoder as rg
    from scipy.spatial import cKDTree

    geocoder = rg.RGeocoder(mode=1, verbose=False)  # 싱글턴 — 이미 만들어져 있으면 그대로 재사용
    kr_locations = [loc for loc in geocoder.locations if loc["cc"] == "KR"]
    coords = [(float(loc["lat"]), float(loc["lon"])) for loc in kr_locations]
    tree = cKDTree(coords)
    _kr_only_index = (tree, kr_locations)
    return _kr_only_index


def _nearest_kr_city(lat: float, lon: float) -> dict:
    tree, kr_locations = _get_kr_only_index()
    _, idx = tree.query((lat, lon), k=1)
    return kr_locations[idx]


def resolve_cities(coords: list[tuple[float, float]]) -> list[Optional[str]]:
    """coords(위도, 경도) 목록을 한 번에 한국어 도시 라벨로 매칭한다(주요
    도시만 번역, 나머지는 로마자 표기 — _localize 참고). 빈 목록이면 빈
    목록. 개별 좌표가 이상해도(예: 범위 밖) reverse_geocoder가 가장 가까운
    지점을 찾아 항상 결과를 반환하므로 None은 나오지 않지만, 시그니처는
    향후 실패 케이스를 대비해 Optional로 둔다."""
    if not coords:
        return []

    import reverse_geocoder as rg

    results = rg.search(coords, mode=1, verbose=False)

    # 한국 영역 안 좌표인데 다른 나라로 매칭됐으면(_get_kr_only_index 참고)
    # 한국 도시로만 다시 찾는다 — 국내 사진이 대부분일 거란 core/geocoder.py
    # 전반의 전제와 같은 이유로, 해외는 이 보정을 하지 않는다(다른 나라의
    # 국경 오탐까지 다 고치려면 나라마다 같은 보정이 필요한데 실사용 빈도가
    # 훨씬 낮음).
    for i, (lat, lon) in enumerate(coords):
        if results[i]["cc"] != "KR" and _in_korea_bbox(lat, lon):
            results[i] = _nearest_kr_city(lat, lon)

    return [_localize(r["name"], r["cc"]) for r in results]
