"""
experiments/geocoder_license_prototype/compare.py

reverse_geocode.py(자체 구현, LGPL 없음)가 reverse_geocoder 패키지(LGPL)와
같은 좌표에 대해 같은 결과를 내는지 검증한다. core/geocoder.py를 실제로 건드리기
전에 먼저 확인하는 1회성 스크립트 (RESTORATION_QUALITY_PLAN.md 5-3, "prototype
before integrating" 원칙).

core/geocoder.py의 한국 보정(_in_korea_bbox, 백령도 등 국경 오탐)과 같은 계열의
케이스도 포함해서, 같은 실패/보정이 그대로 필요한지까지 같이 확인한다.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import reverse_geocode as ours  # noqa: E402

_TEST_COORDS = [
    (37.5665, 126.9780, "서울"),
    (35.1796, 129.0756, "부산"),
    (33.4996, 126.5312, "제주"),
    (40.7128, -74.0060, "New York"),
    (48.8566, 2.3522, "Paris"),
    (35.6762, 139.6503, "Tokyo"),
    (37.9522, 124.6314, "백령도(국경 오탐 재현 케이스, core/geocoder.py:107-109 참고)"),
    (0.0, 0.0, "대서양 한가운데(육지 없음, 극단 케이스)"),
]


def main():
    import reverse_geocoder as rg

    coords = [(lat, lon) for lat, lon, _ in _TEST_COORDS]

    t0 = time.time()
    rg_results = rg.search(coords, mode=1, verbose=False)
    rg_time = time.time() - t0

    t0 = time.time()
    our_results = ours.search(coords)
    our_time = time.time() - t0

    print(f"{'label':45s} {'reverse_geocoder':>25s} {'ours':>25s} {'match':>6s}")
    all_match = True
    for (lat, lon, label), rg_r, our_r in zip(_TEST_COORDS, rg_results, our_results):
        rg_name = f"{rg_r['name']}, {rg_r['cc']}"
        our_name = f"{our_r['name']}, {our_r['cc']}"
        match = rg_name == our_name
        all_match = all_match and match
        print(f"{label:45s} {rg_name:>25s} {our_name:>25s} {'OK' if match else 'DIFF':>6s}")

    print(f"\nreverse_geocoder 로드+검색: {rg_time:.3f}초 / 우리 구현: {our_time:.3f}초")
    print(f"\n전체 일치: {all_match}")


if __name__ == "__main__":
    main()
