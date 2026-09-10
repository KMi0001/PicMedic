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

            # load_image_for_clip()의 축소 디코딩(Image.draft)이 판정을 바꾸지
            # 않는지 — 이게 깨지면 "빠르지만 결과가 달라지는" 최악의 상태가 된다.
            # 디테일이 많은 큰 사진일수록 축소 디코딩에서 정보가 손실될 수 있으므로
            # 단색이 아니라 도형이 잔뜩 있는 폰카 크기 사진으로 확인한다.
            import random

            import torch
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

            model, preprocess, _labels, _tf, device = pc._get_model()

            def embed(tensor):
                with torch.no_grad():
                    f = model.encode_image(tensor.to(device))
                    return f / f.norm(dim=-1, keepdim=True)

            with Image.open(detailed_path) as img:  # 축소 없이 원본 그대로(예전 방식)
                full_tensor = preprocess(img.convert("RGB")).unsqueeze(0)
            drafted_tensor = pc.load_image_for_clip(str(detailed_path), preprocess)

            with Image.open(detailed_path) as img:
                img.draft("RGB", (pc.CLIP_INPUT_SIZE, pc.CLIP_INPUT_SIZE))
                drafted_size = img.size
            check(
                "draft()가 실제로 축소 디코딩을 한다(4032x3024 -> 더 작게)",
                drafted_size[0] < 4032 and drafted_size[0] >= pc.CLIP_INPUT_SIZE,
                drafted_size,
            )

            similarity = float(embed(full_tensor) @ embed(drafted_tensor).T)
            check(
                "축소 디코딩해도 CLIP 임베딩이 사실상 동일(코사인 >= 0.99)",
                similarity >= 0.99,
                round(similarity, 4),
            )


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_photo_category()
    print("OK")
