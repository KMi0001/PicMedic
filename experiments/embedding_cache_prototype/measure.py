"""
experiments/embedding_cache_prototype/measure.py

"동물친구들" 뒤에 "음식 사진" 같은 카테고리를 하나 더 추가할 때, 사진마다
CLIP 이미지 인코딩을 매번 새로 할지(카테고리 기능마다 독립적으로 인코딩을
반복하면 이렇게 됨) 아니면 한 번만 인코딩한 임베딩을 캐싱해서 여러 카테고리
비교에 재사용할지 — 실제로 속도 차이가 얼마나 나는지, 그리고 결과가 정말
동일한지 실측으로 확인하는 1회성 스크립트. 이 실측 결과로 core/image_embedding_cache.py
(임베딩 캐시)를 만들어 core/photo_category.py·core/category_finder.py에
통합했다(2026-09-11).

core/category_finder.py의 "animal" 카테고리(동물 이진 분류)와
core/photo_category.py(8-카테고리 분류) 두 프롬프트셋을 "서로 다른 두
카테고리 기능"으로 놓고 비교한다:
- "매번 재인코딩": 사진마다 이미지를 다시 읽고 인코딩해서 각 프롬프트셋과
  비교(카테고리 기능을 늘릴 때마다 그대로 이렇게 됨).
- "임베딩 캐싱": 사진마다 인코딩을 딱 한 번만 하고, 그 벡터를 두 프롬프트셋
  모두와 비교.

쓰는 자산은 core/category_finder.py·photo_category.py와 동일(assets/photo_category/
ViT-B-32.pt) — 새로 받을 것 없음. 샘플 사진은 experiments/city_organize_prototype/
sample_photos(이미 있는 실사진 7장)를 그대로 쓴다 — 이 스크립트는 "분류
정확도"가 아니라 "캐싱해도 결과가 똑같고 얼마나 빨라지는지"만 검증하는 게
목적이라 사진 내용(동물/음식 여부)은 상관없다.

실행: python experiments/embedding_cache_prototype/measure.py
(프로젝트 루트에서, PicMedic venv 활성화 후)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from core import category_finder, photo_category  # noqa: E402
from core.photo_category import load_image_for_clip  # noqa: E402

_SAMPLE_DIR = Path(__file__).parent.parent / "city_organize_prototype" / "sample_photos"


def main():
    import open_clip
    import torch

    from core.torch_device import resolve_device

    if not category_finder.is_available():
        print("CLIP 자산(assets/photo_category/ViT-B-32.pt)이 없어서 실측을 건너뜁니다.")
        return

    photos = sorted(_SAMPLE_DIR.glob("*.jpg"))
    if not photos:
        print(f"샘플 사진을 못 찾았어요: {_SAMPLE_DIR}")
        return

    from core.image_embedding_cache import _CKPT_PATH

    device = resolve_device()
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(_CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    model = model.to(device)
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    def encode_texts(prompts):
        text = tokenizer(prompts).to(device)
        with torch.no_grad():
            tf = model.encode_text(text)
            tf /= tf.norm(dim=-1, keepdim=True)
        return tf

    # 두 개의 서로 다른 "카테고리 기능" 프롬프트셋 — 동물친구들(이진) +
    # 8-카테고리 사진 분류. "카테고리 기능을 하나 더 추가했다"는 상황을
    # 흉내낸다.
    animal_category = category_finder.CATEGORIES["animal"]
    animal_tf = encode_texts(animal_category.positive_prompts + animal_category.negative_prompts)
    category_tf = encode_texts(list(photo_category._CATEGORIES.values()))

    def encode_image(path):
        tensor = load_image_for_clip(str(path), preprocess).to(device)
        with torch.no_grad():
            f = model.encode_image(tensor)
            f /= f.norm(dim=-1, keepdim=True)
        return f

    def compare(image_features, text_features):
        with torch.no_grad():
            logits = model.logit_scale.exp() * (image_features @ text_features.T).squeeze(0)
            return logits.softmax(dim=-1)

    naive_total = 0.0
    cached_total = 0.0
    mismatches = 0

    print(f"{'file':16s} {'naive(s)':>10s} {'cached(s)':>10s} {'speedup':>9s} {'match':>7s}")
    for path in photos:
        # --- 매번 재인코딩: "찾기" 기능 두 개를 독립적으로 돌렸다고 가정 ---
        t0 = time.perf_counter()
        img_f1 = encode_image(path)
        animal_probs_naive = compare(img_f1, animal_tf)
        img_f2 = encode_image(path)  # 두 번째 기능이 이미지를 다시 인코딩
        category_probs_naive = compare(img_f2, category_tf)
        naive_time = time.perf_counter() - t0

        # --- 임베딩 캐싱: 인코딩은 한 번만, 비교만 두 번 ---
        t0 = time.perf_counter()
        img_f_cached = encode_image(path)
        animal_probs_cached = compare(img_f_cached, animal_tf)
        category_probs_cached = compare(img_f_cached, category_tf)
        cached_time = time.perf_counter() - t0

        naive_total += naive_time
        cached_total += cached_time

        same = torch.allclose(animal_probs_naive, animal_probs_cached, atol=1e-6) and torch.allclose(
            category_probs_naive, category_probs_cached, atol=1e-6
        )
        if not same:
            mismatches += 1

        speedup = naive_time / cached_time if cached_time > 0 else float("inf")
        print(f"{path.name:16s} {naive_time:10.3f} {cached_time:10.3f} {speedup:8.1f}x {'OK' if same else 'DIFF':>7s}")

    print()
    print(f"합계: 재인코딩 {naive_total:.3f}s vs 캐싱 {cached_total:.3f}s -> {naive_total / cached_total:.1f}배")
    print(f"결과 불일치: {mismatches}/{len(photos)}장 (0이어야 캐싱해도 판정이 똑같다는 뜻)")


if __name__ == "__main__":
    main()
