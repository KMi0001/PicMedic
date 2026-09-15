"""
tests/test_image_embedding_cache.py

core/image_embedding_cache.py(CLIP 이미지 인코딩, ONNX Runtime)와
core/category_finder.py(정리 > 카테고리 찾기) 검증.

2026-09-13: 원래 tests/test_photo_category.py에 있던 draft() 축소 디코딩
회귀 테스트를 여기로 옮겼다 — "사진 진단"의 8-카테고리 분류(core/photo_category.py)
기능 자체가 제거됐지만, 이 테스트가 실제로 검증하는 건 photo_category가
아니라 category_finder도 같이 쓰는 공용 임베딩 파이프라인(core/image_embedding_cache.py)
이라 계속 지켜야 하는 커버리지다.

모델 자산이 없으면 is_available() 게이팅 확인까지는 항상 하고, 실제 임베딩
검증은 자산이 있을 때만(없으면 SKIP, tests/test_scanner.py와 같은 방식) 진행한다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check, skip

from PIL import Image

from core import category_finder as cf
from core import image_embedding_cache as iec


def test_image_embedding_cache():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        if not iec.is_available():
            result = cf.detect("landscape", str(tmp / "missing.jpg"))
            check(
                "자산 없을 때 category_finder.detect는 예외 없이 matched=False를 돌려줌",
                result.matched is False,
            )
            skip("실제 CLIP 임베딩 검증 (assets/photo_category/ 없음 — scripts/fetch_photo_category_assets.py + export_clip_onnx_assets.py 필요)")
            return

        # load_image_for_clip()의 축소 디코딩(Image.draft)이 임베딩을 사실상
        # 바꾸지 않는지 — 이게 깨지면 "빠르지만 결과가 달라지는" 최악의 상태가
        # 된다. 디테일이 많은 큰 사진일수록 축소 디코딩에서 정보가 손실될 수
        # 있으므로 단색이 아니라 도형이 잔뜩 있는 폰카 크기 사진으로 확인한다.
        import random

        from PIL import ImageDraw

        random.seed(0)
        detailed = Image.new("RGB", (4032, 3024))
        draw = ImageDraw.Draw(detailed)
        for _ in range(2000):
            x, y = random.randrange(4032), random.randrange(3024)
            draw.ellipse(
                [x, y, x + random.randrange(5, 120), y + random.randrange(5, 120)],
                fill=(random.randrange(256), random.randrange(256), random.randrange(256)),
            )
        detailed_path = tmp / "detailed.jpg"
        detailed.save(detailed_path, quality=92)

        with Image.open(detailed_path) as img:  # 축소 없이 원본 그대로(예전 방식)
            full_tensor = iec._preprocess_pil_image(img.convert("RGB"))
        drafted_tensor = iec.load_image_for_clip(str(detailed_path))

        with Image.open(detailed_path) as img:
            img.draft("RGB", (iec.CLIP_INPUT_SIZE, iec.CLIP_INPUT_SIZE))
            drafted_size = img.size
        check(
            "draft()가 실제로 축소 디코딩을 한다(4032x3024 -> 더 작게)",
            drafted_size[0] < 4032 and drafted_size[0] >= iec.CLIP_INPUT_SIZE,
            drafted_size,
        )

        similarity = float((iec.embed_tensor(full_tensor) @ iec.embed_tensor(drafted_tensor).T)[0, 0])
        check(
            "축소 디코딩해도 CLIP 임베딩이 사실상 동일(코사인 >= 0.99)",
            similarity >= 0.99,
            round(similarity, 4),
        )

        # core/category_finder.py::detect()가 실제로 이 파이프라인을 타고 값을
        # 돌려주는지(카테고리 하나로 충분 — 전체 5개는 experiments/clip_onnx_prototype에서 이미 실측).
        result = cf.detect("landscape", str(detailed_path))
        check("category_finder.detect: confidence는 항상 0~1 사이", 0.0 <= result.confidence <= 1.0, result.confidence)
        check("category_finder.detect: matched는 bool", isinstance(result.matched, bool), result.matched)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_image_embedding_cache()
    print("OK")
