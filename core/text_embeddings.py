"""
core/text_embeddings.py

scripts/export_clip_onnx_assets.py가 미리 계산해둔 카테고리 텍스트 임베딩
(assets/photo_category/text_embeddings.json)을 읽어 numpy 배열로 바꿔주는
로더. core/category_finder.py(5개 카테고리 찾기: 동물친구들 등)가 쓴다 —
카테고리 프롬프트가 코드에 고정값으로 박혀있어서 런타임에 CLIP 텍스트
인코더(torch/open_clip)가 필요 없다(2026-09-13, ONNX 전환과 함께 적용).

원래 "사진 진단"의 8-카테고리 판단(core/photo_category.py)도 같이 썼지만,
그 기능이 통째로 제거되면서(2026-09-13) 지금은 category_finder만 쓴다.

JSON을 다시 만들려면(카테고리 프롬프트를 바꿨을 때) scripts/export_clip_onnx_assets.py를
다시 실행하면 된다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

_PATH = Path(__file__).resolve().parent.parent / "assets" / "photo_category" / "text_embeddings.json"

_cache: dict | None = None


def is_available() -> bool:
    return _PATH.exists()


def load_text_embeddings() -> dict:
    """{"logit_scale": float, "category_finder": {id: {"embeddings": np.ndarray,
    "n_positive": int}}} 형태로 돌려준다(리스트는 numpy 배열로 변환해서 캐싱)."""
    global _cache
    if _cache is not None:
        return _cache

    import numpy as np

    raw = json.loads(_PATH.read_text(encoding="utf-8"))

    category_finder = {
        cat_id: {
            "embeddings": np.array(entry["embeddings"], dtype=np.float32),
            "n_positive": entry["n_positive"],
        }
        for cat_id, entry in raw["category_finder"].items()
    }

    _cache = {
        "logit_scale": raw["logit_scale"],
        "category_finder": category_finder,
    }
    return _cache
