"""
tests/test_photo_category.py

core/photo_category.py(CLIP 기반 카테고리 판단) 검증. 모델 자산이 없으면
classify_photo()가 label=None을 안전하게 돌려주는 것까지는 항상 확인하고,
실제 분류 정확도 확인은 자산이 있을 때만(없으면 SKIP, tests/test_scanner.py와
같은 방식) 진행한다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check, skip

from PIL import Image

from core import photo_category as pc


def test_photo_category():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        blank_path = tmp / "blank.png"
        Image.new("RGB", (300, 300), (128, 128, 128)).save(blank_path)

        if not pc.is_available():
            result = pc.classify_photo(str(blank_path))
            check(
                "자산 없을 때 classify_photo는 예외 없이 label=None을 돌려줌",
                result.label is None,
            )
            skip("실제 CLIP 분류 정확도 확인 (assets/photo_category/ 없음 — scripts/fetch_photo_category_assets.py 필요)")
        else:
            result = pc.classify_photo(str(blank_path))
            check(
                "단색 회색 이미지는 확신 있게 분류되지 않아 label=None",
                result.label is None,
                (result.label, round(result.confidence, 3)),
            )
            check(
                "confidence는 항상 0~1 사이",
                0.0 <= result.confidence <= 1.0,
                result.confidence,
            )


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_photo_category()
    print("OK")
