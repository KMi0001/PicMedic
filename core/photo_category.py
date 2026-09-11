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

2026-09-11: 모델 로딩·이미지 인코딩·`load_image_for_clip`을
core/image_embedding_cache.py로 옮기고 여기서는 그걸 그대로 가져다 쓴다 —
core/category_finder.py("동물친구들"/"음식 사진" 등)와 같은 CLIP 모델·이미지 임베딩을 공유해서
(1) 모델을 두 벌 메모리에 올리지 않고 (2) 사진 한 장을 여러 카테고리
기능이 각각 다시 인코딩하지 않도록 하기 위함(카테고리 기능이 늘어날수록
효과가 커짐 — experiments/embedding_cache_prototype/measure.py 실측).
`is_available`/`load_image_for_clip`/`CLIP_INPUT_SIZE`는 기존 호출부(다른
모듈·tests/test_photo_category.py)가 `photo_category.xxx`로 그대로 쓸 수
있도록 여기서 재노출한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.image_embedding_cache import CLIP_INPUT_SIZE, is_available, load_image_for_clip  # noqa: F401

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

_model_cache = None  # (model, preprocess, labels, text_features, device) 캐시 — 세션 중 반복 호출 시 재로딩 방지


def _get_model():
    """core/image_embedding_cache.get_model()의 공용 CLIP 모델에, 이 파일만의
    8-카테고리 텍스트 임베딩을 얹어 캐싱한다 — tests/test_photo_category.py가
    이 5-튜플 시그니처((model, preprocess, labels, text_features, device))를
    그대로 쓰므로 유지한다."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    import torch

    from core.image_embedding_cache import get_model, get_tokenizer

    model, preprocess, device = get_model()
    tokenizer = get_tokenizer()

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

    from core.image_embedding_cache import get_embedding

    model, _preprocess, labels, text_features, _device = _get_model()
    image_features = get_embedding(path)

    with torch.no_grad():
        logits = model.logit_scale.exp() * (image_features @ text_features.T).squeeze(0)
        probs = logits.softmax(dim=-1)

    idx = int(probs.argmax())
    confidence = float(probs[idx])
    if confidence < CONFIDENCE_THRESHOLD:
        return CategoryResult(label=None, confidence=confidence)
    return CategoryResult(label=labels[idx], confidence=confidence)
