"""
core/category_finder.py

Phase 2 "정리" — 사진 속 내용으로 카테고리를 찾아 모아 보여주는 기능들
("동물친구들", "음식 사진", "스크린샷/문서", "야경 사진", "풍경 사진") 공용
로직. 예전엔 core/cat_finder.py 하나(동물만)였는데, 2026-09-11 사용자 요청으로
카테고리 4개를 더 추가하면서 카테고리마다 파일을 복붙하는 대신 이 모듈
하나로 일반화했다.

core/photo_category.py(8-카테고리 진단용 분류)와 같은 CLIP 모델·이미지
임베딩을 core/image_embedding_cache.py로 공유한다 — 카테고리 기능이 여러
개라도 사진 한 장의 이미지 인코딩은 한 번만 계산되고(같은 세션에서 다른
카테고리 화면이 먼저 본 사진이면 그 결과를 그대로 재사용), 카테고리별
텍스트 비교만 반복한다(실측: experiments/embedding_cache_prototype/measure.py).

카테고리마다 photo_category.py의 8-분류 softmax에 끼워넣지 않고 "이
카테고리" vs "이 카테고리 아님" 이진 프롬프트로 따로 분류한다 — 카테고리가
늘어나도 서로 confidence를 깎아먹지 않고(8-카테고리 쪽에서 실측 확인한
문제), threshold도 카테고리별로 따로 잡을 수 있다.

새 카테고리를 추가하려면: 아래 CATEGORIES에 CategoryDef 하나 추가만 하면
gui/organize_hub_screen.py 카드와 gui/category_finder_screen.py 화면이
자동으로 그 항목까지 만들어준다(둘 다 이 딕셔너리를 순회함).

torch/open_clip은 함수 안에서 지연 import한다 — 다른 AI 기능들과 같은 이유
(앱 시작 속도).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDef:
    id: str
    title: str  # 화면 제목 겸 정리 카드 제목
    card_description: str  # 정리 허브 카드 설명
    hint_text: str  # 화면 상단 안내문구
    empty_text: str  # 찾은 사진이 없을 때 문구
    searching_label: str  # 진행률 팝업 제목("OO 찾는 중")
    output_folder_name: str  # "이 방식대로 정리하기" 기본 저장 폴더명
    positive_prompts: list[str]
    negative_prompts: list[str]
    threshold: float
    color: str  # 검사 결과 표 "카테고리" 컬럼 글자색(한 사진이 카테고리 1개에만 매칭됐을 때만 적용)


# 영어 프롬프트로 정의 — CLIP 텍스트 인코더가 주로 영어로 학습돼 한국어
# 문장보다 정확도가 높다(core/photo_category.py에서 실측 확인한 것과 같은
# 이유). 화면에는 한국어 제목/안내문구만 보여준다.
CATEGORIES: dict[str, CategoryDef] = {
    "animal": CategoryDef(
        id="animal",
        title="동물친구들",
        card_description="AI로 동물이 나온 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
        hint_text=(
            "사진 속 내용을 AI로 추정해서 동물(반려동물 등)이 나온 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        ),
        empty_text="동물이 나온 사진을 찾지 못했어요.",
        searching_label="동물 찾는 중",
        output_folder_name="동물친구들",
        positive_prompts=[
            "a photo of an animal or pet, such as a cat or a dog",
            "a close-up photo of an animal's face",
        ],
        negative_prompts=[
            "a photo with no animal in it",
            "a photo of a person",
            "a photo of a landscape or scenery",
            "a screenshot or a photo of a document with text",
        ],
        threshold=0.6,
        color="#8FA06B",
    ),
    "food": CategoryDef(
        id="food",
        title="음식 사진",
        card_description="AI로 음식이 나온 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
        hint_text=(
            "사진 속 내용을 AI로 추정해서 음식이 나온 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        ),
        empty_text="음식이 나온 사진을 찾지 못했어요.",
        searching_label="음식 사진 찾는 중",
        output_folder_name="음식_사진",
        positive_prompts=[
            "a photo of food",
            "a close-up photo of a dish or meal",
        ],
        negative_prompts=[
            "a photo with no food in it",
            "a photo of a person",
            "a photo of an animal or pet",
            "a screenshot or a photo of a document with text",
        ],
        threshold=0.6,
        color="#D4934F",
    ),
    "document": CategoryDef(
        id="document",
        title="스크린샷/문서",
        card_description="AI로 스크린샷·문서 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
        hint_text=(
            "사진 속 내용을 AI로 추정해서 스크린샷이나 문서가 찍힌 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        ),
        empty_text="스크린샷·문서 사진을 찾지 못했어요.",
        searching_label="스크린샷·문서 찾는 중",
        output_folder_name="스크린샷_문서",
        positive_prompts=[
            "a screenshot of a phone or computer screen",
            "a photo of a document with text",
        ],
        negative_prompts=[
            "a regular photo, not a screenshot or document",
            "a photo of an object or product, not a screenshot",
            "a photo of a person",
            "a photo of a landscape or scenery",
            "a photo of food",
        ],
        threshold=0.6,
        color="#7A7060",
    ),
    "night": CategoryDef(
        id="night",
        title="야경 사진",
        card_description="AI로 야경 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
        hint_text=(
            "사진 속 내용을 AI로 추정해서 밤에 찍은 야경 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        ),
        empty_text="야경 사진을 찾지 못했어요.",
        searching_label="야경 사진 찾는 중",
        output_folder_name="야경_사진",
        positive_prompts=[
            "a nighttime photo, such as a night cityscape or fireworks",
            "a photo taken at night with city lights",
        ],
        negative_prompts=[
            "a daytime photo",
            "a photo of a person",
            "a screenshot or a photo of a document with text",
            "a close-up photo of food",
        ],
        threshold=0.75,
        color="#5C6BC0",
    ),
    "landscape": CategoryDef(
        id="landscape",
        title="풍경 사진",
        card_description="AI로 풍경 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
        hint_text=(
            "사진 속 내용을 AI로 추정해서 풍경 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        ),
        empty_text="풍경 사진을 찾지 못했어요.",
        searching_label="풍경 사진 찾는 중",
        output_folder_name="풍경_사진",
        # 인물/음식/동물/문서와 구분되도록 부정 프롬프트를 그쪽 대표 문구로
        # 채운다 — "풍경"은 나머지 카테고리에 안 걸리는 사진의 기본값에
        # 가까워서(도시 전경도, 자연도 다 풍경) 긍정 프롬프트만으로는
        # 다른 카테고리 사진과 잘 안 갈릴 위험이 있다.
        positive_prompts=[
            "a photo of a landscape or scenery",
            "a wide outdoor photo of nature or a cityscape",
        ],
        negative_prompts=[
            "a close-up photo of a person or a selfie",
            "a screenshot or a photo of a document with text",
            "a close-up photo of food",
            "a close-up photo of an animal's face",
        ],
        threshold=0.55,
        color="#4E9A8F",
    ),
}


@dataclass
class CategoryMatchResult:
    matched: bool
    confidence: float  # 긍정 프롬프트 확률의 합(0~1)


def is_available() -> bool:
    """이 기기에서 카테고리 찾기 기능들을 쓸 수 있는지(자산이 준비됐는지) —
    core/photo_category.py와 같은 자산을 공유하므로 그쪽이 available이면
    이쪽도 항상 available."""
    from core.image_embedding_cache import is_available as _is_available

    return _is_available()


def _get_text_embeddings(category_id: str):
    """scripts/export_clip_onnx_assets.py가 미리 계산해둔 카테고리 텍스트
    임베딩(numpy 배열)을 읽어온다 — 프롬프트가 코드에 고정돼 있어 런타임에
    텍스트 인코더(torch/open_clip)를 띄울 필요가 없다(2026-09-13)."""
    from core.text_embeddings import load_text_embeddings

    data = load_text_embeddings()
    entry = data["category_finder"][category_id]
    return entry["embeddings"], entry["n_positive"], data["logit_scale"]


def detect(category_id: str, path: str) -> CategoryMatchResult:
    """사진 한 장이 이 카테고리에 속하는지 판단한다. 자산이 없으면
    matched=False를 돌려준다 — 호출하는 쪽에서 굳이 is_available()을 먼저
    확인하지 않아도 안전하다."""
    if not is_available():
        return CategoryMatchResult(matched=False, confidence=0.0)

    import numpy as np

    from core.image_embedding_cache import get_embedding

    category = CATEGORIES[category_id]
    text_features, n_positive, logit_scale = _get_text_embeddings(category_id)
    # 이 사진을 다른 카테고리 기능(사진 진단의 카테고리 판단, 다른 "찾기"
    # 화면 등)이 먼저 봤으면 이미지 인코딩을 다시 하지 않고 캐시를 그대로 쓴다.
    image_features = get_embedding(path)

    logits = logit_scale * (image_features @ text_features.T)[0]
    exp = np.exp(logits - logits.max())
    probs = exp / exp.sum()

    confidence = float(probs[:n_positive].sum())
    return CategoryMatchResult(matched=confidence >= category.threshold, confidence=confidence)


def detect_all(path: str) -> dict[str, CategoryMatchResult]:
    """사진 한 장을 CATEGORIES 전체와 한 번에 비교한다 — 이미지 인코딩(비싼
    부분)은 core/image_embedding_cache.py 캐시 덕분에 단 한 번만 하고,
    카테고리별 비교(행렬 곱)만 반복하므로 detect()를 카테고리 수만큼
    호출하는 것과 비교해 오버헤드가 거의 없다. gui/organize_hub_screen.py가
    정리 허브 진입 시 카드마다 배지 개수를 한 번에 채울 때 쓴다."""
    if not is_available():
        return {cat_id: CategoryMatchResult(matched=False, confidence=0.0) for cat_id in CATEGORIES}
    return {cat_id: detect(cat_id, path) for cat_id in CATEGORIES}
