"""
core/cat_finder.py

Phase 2 "정리" — 검사된 사진 중 고양이가 나온 사진만 찾아 모아 보여준다
("고양이 찾기"). core/photo_category.py와 같은 CLIP(open_clip, MIT) zero-shot
분류를 재사용한다 — 새 모델을 따로 받지 않고 이미 앱에 있는 자산
(assets/photo_category/ViT-B-32.pt)만 그대로 쓴다. photo_category.py의 8개
카테고리 중 "동물 사진"은 고양이/개/기타를 구분하지 못해서, 여기서는
"고양이" vs "고양이 아님" 프롬프트로 따로 분류한다.

torchvision 등 물체 탐지(바운딩 박스) 모델은 쓰지 않는다 — Ultralytics
YOLO류는 AGPL 라이선스라 유료 배포 앱에 그대로 못 쓰고(feedback_check_
commercial_license), 이미 검증되어 쓰이고 있는 CLIP 쪽이 더 안전하고 새
자산 다운로드도 필요 없다.

torch/open_clip은 함수 안에서 지연 import한다 — 다른 AI 기능들과 같은 이유
(앱 시작 속도).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CKPT_PATH = _PROJECT_ROOT / "assets" / "photo_category" / "ViT-B-32.pt"

_POSITIVE_PROMPTS = [
    "a photo of a cat",
    "a close-up photo of a cat's face",
]
_NEGATIVE_PROMPTS = [
    "a photo with no cat in it",
    "a photo of a dog",
    "a photo of a person",
    "a photo of a landscape or scenery",
    "a screenshot or a photo of a document with text",
]

# 8-카테고리 분류(core/photo_category.py, threshold 0.4)보다 클래스 수가
# 적어 확률이 덜 퍼져서(이진에 가까움) 더 높게 잡는다 — 배경에 살짝 스친
# 고양이 무늬 담요 같은 애매한 사진까지 "찾았다"고 하지 않기 위함.
CONFIDENCE_THRESHOLD = 0.6

_model_cache = None  # (model, preprocess, text_features, device)


def is_available() -> bool:
    """이 기기에서 고양이 찾기 기능을 쓸 수 있는지(자산이 준비됐는지) —
    core/photo_category.py와 같은 파일을 공유하므로 그쪽이 available이면
    이쪽도 항상 available."""
    return _CKPT_PATH.exists()


def _get_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    import open_clip
    import torch

    from core.torch_device import resolve_device

    device = resolve_device()

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(_CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    model = model.to(device)
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    prompts = _POSITIVE_PROMPTS + _NEGATIVE_PROMPTS
    text = tokenizer(prompts).to(device)
    with torch.no_grad():
        text_features = model.encode_text(text)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    _model_cache = (model, preprocess, text_features, device)
    return _model_cache


@dataclass
class CatDetectionResult:
    is_cat: bool
    confidence: float  # 긍정 프롬프트 확률의 합(0~1)


def detect_cat(path: str) -> CatDetectionResult:
    """사진 한 장에 고양이가 있는지 판단한다. 자산이 없으면(is_available()
    False) is_cat=False를 돌려준다 — 호출하는 쪽에서 굳이 is_available()을
    먼저 확인하지 않아도 안전하다."""
    if not is_available():
        return CatDetectionResult(is_cat=False, confidence=0.0)

    import torch
    from PIL import Image

    model, preprocess, text_features, device = _get_model()

    with Image.open(path) as img:
        tensor = preprocess(img.convert("RGB")).unsqueeze(0).to(device)

    with torch.no_grad():
        image_features = model.encode_image(tensor)
        image_features /= image_features.norm(dim=-1, keepdim=True)
        logits = model.logit_scale.exp() * (image_features @ text_features.T).squeeze(0)
        probs = logits.softmax(dim=-1)

    n_positive = len(_POSITIVE_PROMPTS)
    confidence = float(probs[:n_positive].sum())
    return CatDetectionResult(is_cat=confidence >= CONFIDENCE_THRESHOLD, confidence=confidence)
