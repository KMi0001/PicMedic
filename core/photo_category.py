"""
core/photo_category.py

"사진 진단"에 카테고리 정보를 더한다 — CLIP(OpenAI/open_clip, MIT)으로 사진이
인물/풍경/음식/문서·스크린샷/사물 중 어디에 가까운지 zero-shot으로 판단한다.
고정된 분류기를 새로 학습하는 대신, 각 카테고리를 문장(영어 프롬프트)으로
정의해두고 사진과 가장 잘 맞는 문장을 골라주는 방식이라, 카테고리를 나중에
바꾸거나 추가할 때 재학습이 필요 없다.

open_clip(MIT)의 ViT-B/32, OpenAI 원본 가중치(약 354MB, openaipublic CDN)를
쓴다. 같은 아키텍처의 LAION2B 학습본(약 605MB, plain safetensors)도 있었지만
더 크고, 이 용도(5개 큰 카테고리만 구분)엔 그 정확도 차이가 불필요해서 원본을
골랐다. 원본은 TorchScript(.pt) 아카이브라 torch.load에 weights_only=False가
필요하다 — 우리가 받아서 쓰는 신뢰할 수 있는 자산이라 문제없지만, Python
3.14+에서 torch.jit.load가 더 이상 정식 지원되지 않는다는 FutureWarning이
뜬다(2026-09-07 실측 기준 여전히 동작은 함 — 나중에 깨지면 LAION safetensors
본으로 바꿀 것).

원시 코사인 유사도(-1~1)를 그대로 softmax하면 카테고리 간 차이가 거의 안
보인다(실측: 전부 0.19~0.21대) — CLIP의 학습된 logit_scale(≈100)을 반드시
곱해야 한다(실측: 그제서야 인물사진 85% vs 나머지 1~11%로 벌어짐). 이걸 빠뜨려서
한 번 헤맸다.

torch/open_clip은 이 파일 최상단이 아니라 함수 안에서 지연 import한다 —
다른 AI 기능들과 같은 이유(앱 시작 속도).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CKPT_PATH = _PROJECT_ROOT / "assets" / "photo_category" / "ViT-B-32.pt"

# 영어 프롬프트로 정의 — CLIP 텍스트 인코더가 주로 영어로 학습돼 한국어
# 문장보다 정확도가 높다(실측 확인). 화면에는 왼쪽 한국어 라벨만 보여준다.
# 2026-09-07: 동물/야경/셀카 3개 추가(5→8개) — 카테고리가 늘수록 서로 헷갈리는
# 경우가 늘어 CONFIDENCE_THRESHOLD를 못 넘기는 사진이 많아질 수 있음(트레이드오프
# 안내 후 사용자가 추가를 선택). 특히 "셀카"는 "인물 사진"과 개념이 겹쳐서
# 경계가 애매할 수 있음 — 실사용 확인 후 프롬프트/임계값 조정 필요할 수 있음.
_CATEGORIES: dict[str, str] = {
    "인물 사진": "a photo of a person",
    "셀카": "a selfie photo taken by the person in it, arm's length or front camera",
    "풍경 사진": "a photo of a landscape or scenery",
    "야경 사진": "a nighttime photo, such as a night cityscape or fireworks",
    "음식 사진": "a photo of food",
    "동물 사진": "a photo of an animal or pet",
    "문서/스크린샷": "a screenshot or a photo of a document with text",
    "사물 사진": "a photo of an object or item",
}

# 실측 기준(진짜 가족사진 인물 85% vs 랜덤 노이즈 이미지 38%) — 이보다 낮으면
# "판단하기 어렵다"로 처리한다. 5개 중 가장 그럴듯한 것 하나를 억지로 골라
# 자신 있게 보여주지 않기 위함.
CONFIDENCE_THRESHOLD = 0.4

_model_cache = None  # (model, preprocess, labels, text_features) 캐시 — 세션 중 반복 호출 시 재로딩 방지


def is_available() -> bool:
    """이 기기에서 카테고리 판단 기능을 쓸 수 있는지(가중치 파일이 준비됐는지)."""
    return _CKPT_PATH.exists()


def _get_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    import open_clip
    import torch

    from core.torch_device import resolve_device

    # core/deblur.py·denoise.py·face_restorer.py와 동일한 GPU 자동 감지(공용
    # core/torch_device.resolve_device) — 이 함수만 빠져 있어서 GPU가 있는
    # 기기에서도 항상 CPU로 돌고 있었다(실측: 4032x3024 기준 CPU 215ms/장,
    # 사진 진단의 카테고리 판단도 이 경로를 타므로 같이 빨라진다).
    device = resolve_device()

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(_CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    model = model.to(device)
    tokenizer = open_clip.get_tokenizer("ViT-B-32")

    labels = list(_CATEGORIES.keys())
    text = tokenizer(list(_CATEGORIES.values())).to(device)
    with torch.no_grad():
        text_features = model.encode_text(text)
        text_features /= text_features.norm(dim=-1, keepdim=True)

    _model_cache = (model, preprocess, labels, text_features, device)
    return _model_cache


@dataclass
class CategoryResult:
    label: str | None  # 확신이 낮으면(CONFIDENCE_THRESHOLD 미만) None
    confidence: float


def classify_photo(path: str) -> CategoryResult:
    """사진 한 장의 카테고리를 판단한다. 자산이 없으면(is_available() False)
    label=None을 돌려준다 — 호출하는 쪽에서 굳이 is_available()을 먼저
    확인하지 않아도 안전하다."""
    if not is_available():
        return CategoryResult(label=None, confidence=0.0)

    import torch
    from PIL import Image

    model, preprocess, labels, text_features, device = _get_model()

    with Image.open(path) as img:
        tensor = preprocess(img.convert("RGB")).unsqueeze(0).to(device)

    with torch.no_grad():
        image_features = model.encode_image(tensor)
        image_features /= image_features.norm(dim=-1, keepdim=True)
        logits = model.logit_scale.exp() * (image_features @ text_features.T).squeeze(0)
        probs = logits.softmax(dim=-1)

    idx = int(probs.argmax())
    confidence = float(probs[idx])
    if confidence < CONFIDENCE_THRESHOLD:
        return CategoryResult(label=None, confidence=confidence)
    return CategoryResult(label=labels[idx], confidence=confidence)
