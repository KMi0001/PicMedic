"""
experiments/deblur_safety_prototype/verify_gate.py

core/deblur.py에 방금 넣은 사전/사후 안전장치가 실측 데이터대로 동작하는지
빠르게 확인하는 1회성 스크립트 (measure.py로 잡은 케이스 재사용).

기대:
- old_blurry_portrait.jpg: 정상 처리 성공 (사전점검 통과 + 사후점검 통과)
- busan.jpg: 사후점검에서 DeblurResultUnstableError로 막힘 (모델까지는 갔지만 결과 폐기)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from core import deblur  # noqa: E402

_TEST_DIR = Path(__file__).parent.parent / "restore_prototype" / "test_images"
_CITY_DIR = Path(__file__).parent.parent / "city_organize_prototype" / "sample_photos"

CASES = [
    ("정상 처리 기대", _TEST_DIR / "old_blurry_portrait.jpg"),
    ("사후점검 차단 기대", _CITY_DIR / "busan.jpg"),
]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for label, path in CASES:
            print(f"\n--- {label}: {path.name} ---")
            try:
                out = deblur.deblur_image(str(path), tmp, suffix="gatetest")
                print(f"  성공: {out}")
            except deblur.DeblurNotRecommendedError as exc:
                print(f"  사전점검 차단: {exc}")
            except deblur.DeblurResultUnstableError as exc:
                print(f"  사후점검 차단: {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"  예상 못한 예외: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
