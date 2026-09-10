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

from core.geocoder import resolve_cities


def run():
    passed = failed = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

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

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
