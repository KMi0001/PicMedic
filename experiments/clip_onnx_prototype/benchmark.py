"""
experiments/clip_onnx_prototype/benchmark.py

"AI 카테고리 찾기/사진 진단"이 쓰는 CLIP(ViT-B-32) 이미지 인코더를 세 가지
방식으로 실측 비교하는 일회성 프로토타입:
    1) PyTorch fp32 (현재 core/image_embedding_cache.py가 쓰는 방식)
    2) ONNX Runtime fp32 (같은 가중치, 추론 엔진만 교체)
    3) ONNX Runtime INT8 동적 양자화

측정 항목: 모델 파일 크기 / 이미지당 인코딩 속도 / 임베딩 코사인 유사도
(PyTorch 대비) / core/category_finder.py의 실제 5개 카테고리 판정이 백엔드
간에 달라지는지(뒤집힘 개수).

실행:
    python experiments/clip_onnx_prototype/benchmark.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CKPT_PATH = PROJECT_ROOT / "assets" / "photo_category" / "ViT-B-32.pt"
OUT_DIR = Path(__file__).resolve().parent
ONNX_FP32_PATH = OUT_DIR / "clip_visual_fp32.onnx"
ONNX_INT8_PATH = OUT_DIR / "clip_visual_int8.onnx"

N_SYNTHETIC = 150
WARMUP = 5

# 실제 사진 내용이 아니라 스캔 파이프라인 테스트용 손상/비이미지 픽스처라
# 이 벤치마크(정상 이미지 인코딩 속도·분류 결과 비교)와 무관한 폴더는 제외.
SKIP_DIR_NAMES = {"08_손상_헤더손상", "09_손상_부분손상", "10_손상_크기0", "11_이미지아닌파일", "_check_out"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif"}


USER_PHOTOS_DIR = OUT_DIR / "user_photos"


def collect_real_images() -> list[Path]:
    """test_samples(대부분 비어있는 테스트 픽스처) + user_photos(검증용으로
    직접 넣어둔 실제 사진, git에는 안 올라감)를 합쳐서 돌려준다."""
    search_dirs = [PROJECT_ROOT / "test_samples", USER_PHOTOS_DIR]
    candidates = []
    for base in search_dirs:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
                continue
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            candidates.append(p)

    paths = []
    for p in candidates:
        try:
            with Image.open(p) as img:
                img.convert("RGB")
        except Exception:
            continue
        paths.append(p)
    skipped = len(candidates) - len(paths)
    if skipped:
        print(f"(디코딩 실패로 제외된 샘플 {skipped}개)")
    return paths


def make_synthetic_images(n: int) -> list[Path]:
    """속도 측정용 — 실제 아이폰 사진과 비슷한 해상도(4032x3024)의 랜덤
    이미지. 내용은 무의미하지만 인코딩 파이프라인(디코딩+전처리+forward)
    부하는 실제 사진과 동일하다."""
    out_dir = OUT_DIR / "_synthetic"
    out_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(n):
        path = out_dir / f"synth_{i}.jpg"
        if not path.exists():
            rng = np.random.default_rng(i)
            arr = rng.integers(0, 255, (3024, 4032, 3), dtype=np.uint8)
            Image.fromarray(arr, "RGB").save(path, quality=90)
        paths.append(path)
    return paths


def load_pytorch_model():
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained=str(CKPT_PATH), force_quick_gelu=True, weights_only=False
    )
    model.eval()
    return model, preprocess


def load_image_tensor(path: Path, preprocess):
    with Image.open(path) as img:
        img.draft("RGB", (224, 224))
        return preprocess(img.convert("RGB")).unsqueeze(0)


def export_onnx(model) -> None:
    import torch

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


def quantize_onnx() -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(str(ONNX_FP32_PATH), str(ONNX_INT8_PATH), weight_type=QuantType.QUInt8)


def bench_pytorch(model, preprocess, paths: list[Path]):
    import torch

    tensors = [load_image_tensor(p, preprocess) for p in paths]
    with torch.no_grad():
        for t in tensors[:WARMUP]:
            model.encode_image(t)
        start = time.perf_counter()
        feats = []
        for t in tensors:
            f = model.encode_image(t)
            f = f / f.norm(dim=-1, keepdim=True)
            feats.append(f.numpy())
        elapsed = time.perf_counter() - start
    return np.concatenate(feats, axis=0).astype(np.float32), elapsed


def bench_onnx(onnx_path: Path, preprocess, paths: list[Path]):
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    tensors = [load_image_tensor(p, preprocess).numpy() for p in paths]

    for t in tensors[:WARMUP]:
        sess.run(None, {input_name: t})

    start = time.perf_counter()
    feats = []
    for t in tensors:
        out = sess.run(None, {input_name: t})[0]
        out = out / np.linalg.norm(out, axis=-1, keepdims=True)
        feats.append(out)
    elapsed = time.perf_counter() - start
    return np.concatenate(feats, axis=0).astype(np.float32), elapsed


def cosine_sim_mean(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.sum(a * b, axis=-1)))


def build_text_features(model):
    """core/category_finder.py의 5개 카테고리 프롬프트를 그대로 인코딩 —
    텍스트 인코더는 백엔드 교체 대상이 아니므로(사진 1장당 비용이 아니라
    카테고리당 1회뿐) PyTorch로 고정."""
    import torch

    from core.category_finder import CATEGORIES

    tokenizer_module = __import__("open_clip")
    tokenizer = tokenizer_module.get_tokenizer("ViT-B-32")

    result = {}
    with torch.no_grad():
        for cat_id, cat in CATEGORIES.items():
            prompts = cat.positive_prompts + cat.negative_prompts
            text = tokenizer(prompts)
            text_features = model.encode_text(text)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            result[cat_id] = (text_features.numpy().astype(np.float32), len(cat.positive_prompts), cat.threshold)
    return result


def confidence_scores(image_feats: np.ndarray, text_features: np.ndarray, n_positive: int, logit_scale: float) -> np.ndarray:
    logits = logit_scale * (image_feats @ text_features.T)
    exp = np.exp(logits - logits.max(axis=-1, keepdims=True))
    probs = exp / exp.sum(axis=-1, keepdims=True)
    return probs[:, :n_positive].sum(axis=-1)


def main() -> int:
    print("=== 1. 모델 로드 & 샘플 이미지 준비 ===")
    model, preprocess = load_pytorch_model()
    logit_scale = float(model.logit_scale.exp().item())

    real_images = collect_real_images()
    synthetic_images = make_synthetic_images(N_SYNTHETIC)
    all_images = real_images + synthetic_images
    print(f"실제 샘플 {len(real_images)}장 + 합성 이미지 {len(synthetic_images)}장 = 총 {len(all_images)}장")

    print("\n=== 2. ONNX 변환 & 양자화 ===")
    if not ONNX_FP32_PATH.exists():
        export_onnx(model)
    if not ONNX_INT8_PATH.exists():
        quantize_onnx()

    pt_size = CKPT_PATH.stat().st_size / 1e6
    onnx_fp32_size = ONNX_FP32_PATH.stat().st_size / 1e6
    onnx_int8_size = ONNX_INT8_PATH.stat().st_size / 1e6
    print(f"PyTorch 체크포인트(전체, vision+text): {pt_size:.1f} MB")
    print(f"ONNX fp32 (vision encoder만): {onnx_fp32_size:.1f} MB")
    print(f"ONNX int8 (vision encoder만): {onnx_int8_size:.1f} MB")

    print("\n=== 3. 속도 측정 (전체 이미지) ===")
    pt_feats, pt_time = bench_pytorch(model, preprocess, all_images)
    print(f"① PyTorch fp32   : {pt_time:.2f}s  ({len(all_images) / pt_time:.2f} images/sec)")

    onnx_feats, onnx_time = bench_onnx(ONNX_FP32_PATH, preprocess, all_images)
    print(f"② ONNX fp32      : {onnx_time:.2f}s  ({len(all_images) / onnx_time:.2f} images/sec)")

    int8_feats, int8_time = bench_onnx(ONNX_INT8_PATH, preprocess, all_images)
    print(f"③ ONNX int8      : {int8_time:.2f}s  ({len(all_images) / int8_time:.2f} images/sec)")

    print("\n=== 4. 임베딩 정확도 (PyTorch 대비 코사인 유사도, 1.0=완전 동일) ===")
    print(f"② ONNX fp32 vs ①: {cosine_sim_mean(pt_feats, onnx_feats):.6f}")
    print(f"③ ONNX int8 vs ①: {cosine_sim_mean(pt_feats, int8_feats):.6f}")

    print("\n=== 5. 실제 카테고리 판정 비교 (실제 샘플 이미지만, 5개 카테고리) ===")
    text_features_by_cat = build_text_features(model)
    n_real = len(real_images)
    total_checks = 0
    total_flips_fp32 = 0
    total_flips_int8 = 0
    # threshold에서 이 폭(±0.1) 안에 든 confidence는 "경계선 사진"으로 본다 —
    # 원래도 애매해서 뒤집히기 쉬운 사진들이라, 여기서 특히 int8 안정성을 본다.
    BORDER_MARGIN = 0.1
    borderline_reports = []

    for cat_id, (text_feats, n_pos, threshold) in text_features_by_cat.items():
        pt_conf = confidence_scores(pt_feats[:n_real], text_feats, n_pos, logit_scale)
        onnx_conf = confidence_scores(onnx_feats[:n_real], text_feats, n_pos, logit_scale)
        int8_conf = confidence_scores(int8_feats[:n_real], text_feats, n_pos, logit_scale)

        pt_match = pt_conf >= threshold
        onnx_match = onnx_conf >= threshold
        int8_match = int8_conf >= threshold

        flips_fp32 = int(np.sum(pt_match != onnx_match))
        flips_int8 = int(np.sum(pt_match != int8_match))
        total_checks += n_real
        total_flips_fp32 += flips_fp32
        total_flips_int8 += flips_int8
        print(f"  {cat_id:10s}: ONNX fp32 뒤집힘 {flips_fp32}/{n_real}, int8 뒤집힘 {flips_int8}/{n_real}")

        for i in range(n_real):
            if abs(pt_conf[i] - threshold) < BORDER_MARGIN:
                borderline_reports.append(
                    (real_images[i].name, cat_id, threshold, pt_conf[i], onnx_conf[i], int8_conf[i])
                )

    print(f"\n합계: ONNX fp32 뒤집힘 {total_flips_fp32}/{total_checks}, int8 뒤집힘 {total_flips_int8}/{total_checks}")

    print(f"\n=== 6. 경계선 사진 상세 (threshold ±{BORDER_MARGIN} 이내, 원래도 애매한 사진들) ===")
    if not borderline_reports:
        print("경계선에 걸친 사진 없음 (표본이 작아서일 수 있음 — user_photos에 사진을 더 추가하면 더 잘 드러남)")
    else:
        for name, cat_id, threshold, pt_c, onnx_c, int8_c in borderline_reports:
            print(
                f"  {name} [{cat_id}] threshold={threshold:.2f} | "
                f"PyTorch={pt_c:.3f} ONNX={onnx_c:.3f} int8={int8_c:.3f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
