"""
core/image_embedding_cache.py

CLIP(open_clip, MIT, ViT-B-32, assets/photo_category/ViT-B-32.pt) 모델 로딩과
사진별 이미지 임베딩을 core/photo_category.py(8-카테고리 분류)와
core/category_finder.py(동물친구들/음식 사진 등 카테고리 이진 분류)가 공유하도록 모아둔 곳.

이전엔 두 파일이 각자 따로 모델을 로드하고(같은 가중치가 메모리에 두 벌
올라감) 사진마다 이미지를 새로 인코딩했다. 카테고리 판단 기능("정리 > 동물
친구들" 뒤로 다른 카테고리 기능이 늘어날 걸 염두에 두고) 늘어날수록
사진 한 장을 여러 카테고리 프롬프트셋과 비교하게 되는데, CLIP에서 정말
비싼 부분은 이미지 인코딩(신경망 forward)이고 임베딩을 텍스트와 비교하는
건(행렬 하나 곱하기) 사실상 공짜다. 그래서 이미지 인코딩 결과만 경로별로
캐싱해두면 카테고리 기능이 몇 개든 사진당 인코딩은 한 번만 하면 된다 —
실측 확인(experiments/embedding_cache_prototype/measure.py): 카테고리 2개
기준 약 2배 빨라지고, 캐싱 여부와 무관하게 판정 결과는 완전히 동일(같은
결정적 연산이라 순서가 결과에 영향을 주지 않음).

메모리: 임베딩 1장당 512 floats(2KB) — 사진 3만 장이어도 약 60MB로 부담
없는 수준이라 세션 동안은 자유롭게 쌓아둔다. 앱을 재시작하면 초기화되고
디스크에는 저장하지 않는다 — 그 정도로 캐싱할 필요는 없다고 판단(세션 중
같은 사진을 여러 카테고리 기능이 다시 보는 경우만 빠르게 하면 충분).

torch/open_clip은 함수 안에서 지연 import한다 — 다른 AI 기능들과 같은 이유
(앱 시작 속도).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CKPT_PATH = _PROJECT_ROOT / "assets" / "photo_category" / "ViT-B-32.pt"

# CLIP이 실제로 보는 입력 크기. preprocess가 어차피 여기까지 줄이므로, 그보다
# 큰 해상도로 디코딩하는 건 전부 버리는 일이다 — load_image_for_clip 참고.
CLIP_INPUT_SIZE = 224

_model_cache = None  # (model, preprocess, device)
_embedding_cache: dict[str, "torch.Tensor"] = {}


def is_available() -> bool:
    """이 기기에서 CLIP 기반 카테고리 판단(사진 분류·동물친구들 등)을 쓸 수
    있는지(가중치 파일이 준비됐는지)."""
    return _CKPT_PATH.exists()


def load_image_for_clip(path: str, preprocess):
    """사진 한 장을 CLIP 입력 텐서로 만든다. photo_category(사진 진단 카테고리)와
    category_finder(동물친구들/음식 사진 등)가 같은 자산·같은 전처리를 쓰므로 여기 하나로 둔다.

    Image.draft()로 축소 디코딩한다 — CLIP이 실제로 보는 건 224x224뿐이라
    수천만 화소 원본을 그대로 디코딩하는 건 낭비다(실측: 4032x3024 기준
    CPU 디코딩 시간이 크게 줄고, 임베딩 코사인 유사도는 0.99+ 로 사실상
    결과가 바뀔 여지가 없다. tests/test_photo_category.py에 회귀 테스트로
    남겨뒀다)."""
    from PIL import Image

    with Image.open(path) as img:
        img.draft("RGB", (CLIP_INPUT_SIZE, CLIP_INPUT_SIZE))
        return preprocess(img.convert("RGB")).unsqueeze(0)


def get_model():
    """(model, preprocess, device) — photo_category.py·category_finder.py가 공유한다.
    둘 다 화면에 같이 뜨는 세션(예: 화질 개선 + 동물친구들)이면 예전엔 CLIP
    가중치(약 350MB)가 메모리에 두 벌 올라갔었다."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    import open_clip

    from core.torch_device import resolve_device

    device = resolve_device()

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(_CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    model = model.to(device)

    _model_cache = (model, preprocess, device)
    return _model_cache


def get_tokenizer():
    import open_clip

    return open_clip.get_tokenizer("ViT-B-32")


def get_embedding(path: str):
    """사진 한 장의 CLIP 이미지 임베딩(정규화된 512차원 벡터, 1x512 텐서)을
    돌려준다. 같은 세션에서 다른 카테고리 기능이 이 사진을 이미 본 적
    있으면 인코딩을 다시 하지 않고 캐시에서 그대로 꺼내 쓴다."""
    import torch

    cached = _embedding_cache.get(path)
    if cached is not None:
        return cached

    model, preprocess, device = get_model()
    tensor = load_image_for_clip(path, preprocess).to(device)
    with torch.no_grad():
        features = model.encode_image(tensor)
        features /= features.norm(dim=-1, keepdim=True)

    _embedding_cache[path] = features
    return features
