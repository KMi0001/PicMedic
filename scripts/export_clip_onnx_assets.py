"""
scripts/export_clip_onnx_assets.py

assets/photo_category/ViT-B-32.pt(PyTorch CLIP 체크포인트, 354MB)에서
런타임에 실제로 필요한 것만 뽑아 훨씬 가벼운 자산으로 바꾼다(2026-09-13,
experiments/clip_onnx_prototype 실측 후 적용):

    1) 비전 인코더만 ONNX로 export → INT8 동적 양자화 (338M → 약 89M)
    2) core/category_finder.py(카테고리 찾기: 동물친구들 등)가 쓰는 카테고리
       프롬프트를 전부 텍스트 인코딩해서 결과 벡터만 JSON으로 저장 — 카테고리
       프롬프트가 고정값이라 런타임에 텍스트 인코더(=torch/open_clip)가 아예
       필요 없어진다.

2026-09-13: "사진 진단"(core/photo_category.py의 8-카테고리 판단)이 통째로
제거되면서, 여기서 인코딩하는 프롬프트는 category_finder 것만 남았다.

런타임(core/image_embedding_cache.py)은 이 스크립트가 만든 두 자산
(clip_visual_int8.onnx, text_embeddings.json)만 onnxruntime으로 읽는다 —
torch/open_clip은 이 스크립트(모델을 다시 export해야 할 때만) 전용이라
requirements-dev.txt에만 있다.

실행 (개발 환경에 torch/open_clip/onnx가 설치돼 있어야 함):
    python scripts/export_clip_onnx_assets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ASSETS_DIR = PROJECT_ROOT / "assets" / "photo_category"
CKPT_PATH = ASSETS_DIR / "ViT-B-32.pt"
ONNX_FP32_PATH = ASSETS_DIR / "_clip_visual_fp32_tmp.onnx"  # 중간 산출물, 끝나면 삭제
ONNX_INT8_PATH = ASSETS_DIR / "clip_visual_int8.onnx"
TEXT_EMBEDDINGS_PATH = ASSETS_DIR / "text_embeddings.json"


def load_pytorch_model():
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    return model, preprocess


def export_and_quantize(model) -> None:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    dummy = torch.randn(1, 3, 224, 224)
    torch.onnx.export(
        model.visual,
        dummy,
        str(ONNX_FP32_PATH),
        input_names=["pixel_values"],
        output_names=["image_features"],
        opset_version=17,
        dynamo=False,
    )
    quantize_dynamic(str(ONNX_FP32_PATH), str(ONNX_INT8_PATH), weight_type=QuantType.QUInt8)
    ONNX_FP32_PATH.unlink()


def export_text_embeddings(model) -> None:
    """core/category_finder.py(5개 카테고리, 이진 프롬프트)가 쓰는 모든 텍스트
    프롬프트를 인코딩해서 저장한다 — 프롬프트가 코드에 고정돼 있으므로
    런타임에 다시 인코딩할 필요가 없다."""
    import open_clip
    import torch

    from core.category_finder import CATEGORIES as CATEGORY_FINDER_DEFS

    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    logit_scale = float(model.logit_scale.exp().item())

    def encode(prompts: list[str]) -> list[list[float]]:
        with torch.no_grad():
            text = tokenizer(prompts)
            features = model.encode_text(text)
            features /= features.norm(dim=-1, keepdim=True)
        return features.numpy().tolist()

    category_finder = {}
    for cat_id, cat in CATEGORY_FINDER_DEFS.items():
        prompts = cat.positive_prompts + cat.negative_prompts
        category_finder[cat_id] = {
            "n_positive": len(cat.positive_prompts),
            "threshold": cat.threshold,
            "embeddings": encode(prompts),
        }

    payload = {
        "logit_scale": logit_scale,
        "category_finder": category_finder,
    }
    TEXT_EMBEDDINGS_PATH.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    if not CKPT_PATH.exists():
        print(f"먼저 python scripts/fetch_photo_category_assets.py로 {CKPT_PATH}를 받아주세요.")
        return 1

    print("PyTorch 모델 로드 중...")
    model, _preprocess = load_pytorch_model()

    print("ONNX export + INT8 양자화 중...")
    export_and_quantize(model)
    print(f"저장: {ONNX_INT8_PATH} ({ONNX_INT8_PATH.stat().st_size / 1e6:.1f} MB)")

    print("카테고리 텍스트 임베딩 계산 중...")
    export_text_embeddings(model)
    print(f"저장: {TEXT_EMBEDDINGS_PATH} ({TEXT_EMBEDDINGS_PATH.stat().st_size / 1e3:.1f} KB)")

    print(f"\n이제 {CKPT_PATH.name}은 런타임에 필요 없습니다 — 삭제해도 됩니다")
    print("(재변환이 필요할 때만 fetch_photo_category_assets.py로 다시 받으세요).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
