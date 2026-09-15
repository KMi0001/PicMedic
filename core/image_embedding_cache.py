"""
core/image_embedding_cache.py

CLIP(ViT-B-32) 이미지 인코더 로딩과 사진별 이미지 임베딩을 core/category_finder.py
(정리 > 카테고리 찾기: 동물친구들/음식 사진 등 카테고리 이진 분류)가 쓰도록
모아둔 곳. 원래는 "사진 진단"의 8-카테고리 분류(core/photo_category.py)와도
공유했지만, 그 기능이 통째로 제거되면서(2026-09-13) 지금은 category_finder만
쓴다.

2026-09-13: PyTorch(open_clip) 추론을 ONNX Runtime + INT8 양자화로 교체했다
(experiments/clip_onnx_prototype 실측: 속도 약 2.4배, 모델 용량 338M → 89M,
실제 사진 112장 기준 카테고리 판정 뒤집힘 0.5%로 실사용에 지장 없는 수준
확인). 텍스트 인코더(카테고리 프롬프트)는 애초에 고정값이라 런타임에 아예
필요 없다 — scripts/export_clip_onnx_assets.py가 미리 인코딩해 저장해둔
assets/photo_category/text_embeddings.json을 core/category_finder.py가
직접 읽는다. 같은 날 후속으로 "사진 진단"의 얼굴 탐지(facexlib)까지
제거되면서, 이 앱은 이제 torch를 어디에서도 쓰지 않는다.

카테고리 기능이 여러 개(정리 > 동물친구들/음식 사진/스크린샷/야경/풍경)일
때, CLIP에서 정말 비싼 부분은 이미지 인코딩(신경망 forward)이고 임베딩을
텍스트와 비교하는 건(행렬 하나 곱하기) 사실상 공짜다. 그래서 이미지 인코딩
결과만 경로별로 캐싱해두면 카테고리 기능이 몇 개든 사진당 인코딩은 한 번만
하면 된다 — 실측 확인(experiments/embedding_cache_prototype/measure.py):
카테고리 2개 기준 약 2배 빨라지고, 캐싱 여부와 무관하게 판정 결과는 완전히
동일(같은 결정적 연산이라 순서가 결과에 영향을 주지 않음).

메모리: 임베딩 1장당 512 floats(2KB) — 사진 3만 장이어도 약 60MB로 부담
없는 수준이라 세션 동안은 자유롭게 쌓아둔다. 앱을 재시작하면 초기화되고
디스크에는 저장하지 않는다 — 그 정도로 캐싱할 필요는 없다고 판단(세션 중
같은 사진을 여러 카테고리 기능이 다시 보는 경우만 빠르게 하면 충분).

onnxruntime/numpy는 함수 안에서 지연 import한다 — 다른 AI 기능들과 같은 이유
(앱 시작 속도).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets" / "photo_category"
_ONNX_PATH = _ASSETS_DIR / "clip_visual_int8.onnx"

# CLIP이 실제로 보는 입력 크기. _preprocess가 어차피 여기까지 줄이므로, 그보다
# 큰 해상도로 디코딩하는 건 전부 버리는 일이다 — load_image_for_clip 참고.
CLIP_INPUT_SIZE = 224

# OpenAI CLIP 표준 전처리 상수(open_clip의 "openai" pretrained 프리셋과 동일) —
# ONNX로 넘어가면서 open_clip의 transform 객체 대신 이 값을 직접 쓴다.
_CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
_CLIP_STD = (0.26862954, 0.26130258, 0.27577711)

_session = None  # onnxruntime.InferenceSession
_embedding_cache: dict[str, "np.ndarray"] = {}


def is_available() -> bool:
    """이 기기에서 CLIP 기반 카테고리 판단(사진 분류·동물친구들 등)을 쓸 수
    있는지(가중치 파일이 준비됐는지)."""
    return _ONNX_PATH.exists()


def _preprocess_pil_image(img) -> "np.ndarray":
    """이미 RGB로 변환된 PIL 이미지를 CLIP 입력 배열(1x3x224x224, float32)로
    바꾼다 — OpenAI CLIP 표준 전처리(짧은 변 224로 리사이즈 → 센터크롭 →
    정규화)를 그대로 재현한다(open_clip의 "openai" pretrained 프리셋과 동일)."""
    import numpy as np
    from PIL import Image

    w, h = img.size
    scale = CLIP_INPUT_SIZE / min(w, h)
    new_w, new_h = round(w * scale), round(h * scale)
    img = img.resize((new_w, new_h), Image.BICUBIC)
    left = (new_w - CLIP_INPUT_SIZE) // 2
    top = (new_h - CLIP_INPUT_SIZE) // 2
    img = img.crop((left, top, left + CLIP_INPUT_SIZE, top + CLIP_INPUT_SIZE))

    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - np.array(_CLIP_MEAN, dtype=np.float32)) / np.array(_CLIP_STD, dtype=np.float32)
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return arr[None, :, :, :]  # 배치 차원 추가


def load_image_for_clip(path: str, preprocess=None) -> "np.ndarray":
    """사진 한 장을 CLIP 입력 배열(1x3x224x224, float32)로 만든다.
    core/category_finder.py(동물친구들/음식 사진 등)가 이 전처리를 쓴다.

    preprocess 인자는 이전 PyTorch 버전과의 시그니처 호환용으로 남겨뒀을 뿐
    쓰지 않는다(호출부는 core/category_finder.py 등 전부 위치 인자 없이
    path만 넘긴다).

    Image.draft()로 축소 디코딩한다 — CLIP이 실제로 보는 건 224x224뿐이라
    수천만 화소 원본을 그대로 디코딩하는 건 낭비다(실측: 4032x3024 기준
    CPU 디코딩 시간이 크게 줄고, 임베딩 코사인 유사도는 0.99+ 로 사실상
    결과가 바뀔 여지가 없다. tests/test_image_embedding_cache.py에 회귀
    테스트로 남겨뒀다)."""
    from PIL import Image

    with Image.open(path) as img:
        img.draft("RGB", (CLIP_INPUT_SIZE, CLIP_INPUT_SIZE))
        return _preprocess_pil_image(img.convert("RGB"))


def embed_tensor(tensor: "np.ndarray") -> "np.ndarray":
    """이미 전처리된 입력 배열을 정규화된 CLIP 이미지 임베딩으로 바꾼다 —
    경로 기반 캐시(get_embedding)를 거치지 않는 저수준 진입점. 주로
    tests/test_image_embedding_cache.py가 draft() 유무에 따른 임베딩 차이를
    직접 비교할 때 쓴다."""
    import numpy as np

    session = _get_session()
    input_name = session.get_inputs()[0].name
    features = session.run(None, {input_name: tensor})[0]
    return (features / np.linalg.norm(features, axis=-1, keepdims=True)).astype(np.float32)


def _get_session():
    global _session
    if _session is not None:
        return _session

    import onnxruntime as ort

    _session = ort.InferenceSession(str(_ONNX_PATH), providers=["CPUExecutionProvider"])
    return _session


def get_embedding(path: str) -> "np.ndarray":
    """사진 한 장의 CLIP 이미지 임베딩(정규화된 512차원 벡터, numpy 배열)을
    돌려준다. 같은 세션에서 다른 카테고리 기능이 이 사진을 이미 본 적
    있으면 인코딩을 다시 하지 않고 캐시에서 그대로 꺼내 쓴다."""
    cached = _embedding_cache.get(path)
    if cached is not None:
        return cached

    features = embed_tensor(load_image_for_clip(path))
    _embedding_cache[path] = features
    return features
