"""
experiments/denoise_safety_prototype/measure.py

디노이즈 사전/사후 안전장치용 임계값을 실측으로 정하는 1회성 스크립트.
experiments/deblur_safety_prototype/measure.py와 같은 목적, 디노이즈용.

사전 점검: quality_diagnosis.assess_quality_issues()가 쓰는 것과 같은 노이즈
지표(중앙 400x400 크롭 + 3x3 미디언필터 잔차 stddev, NOISE_RESIDUAL_STDDEV_THRESHOLD
= 5.0)로 "노이즈 추정"이 아닌 입력을 거른다 — 이건 이미 실측 튜닝된 상수를 그대로
재사용하는 것이라 여기서 새로 정할 필요는 없고, 후보 이미지들이 이 기준으로
어떻게 갈리는지만 확인한다.

사후 점검: core/deblur.py와 동일한 지표(전역 edge variance 비율)로 출력이
입력 대비 얼마나 벌어지는지 측정한다. 실측 재료:
1) 도시 사진(정상, 노이즈 적음) — 사전 점검에서 걸러져야 정상.
2) 위 사진에 인위적으로 가우시안 노이즈를 더한 버전 — "진짜 노이즈 있는 입력"의
   대역적 근사치(SIDD 실측 사진은 아니지만, 사전 점검을 통과시켜 모델에 넣어볼
   수 있는 유일한 재료). 정상 케이스의 ratio 상한을 가늠하는 용도.
3) 순수 랜덤 노이즈 이미지 — 모델 입장에서 가장 심하게 도메인을 벗어난 입력.
   망가짐의 상한(ratio가 얼마나 폭주할 수 있는지)을 가늠하는 용도.

실행: python experiments/denoise_safety_prototype/measure.py
(프로젝트 루트에서, PicMedic venv 활성화 후)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageChops, ImageFilter, ImageStat  # noqa: E402

from core import denoise  # noqa: E402
from core.quality_diagnosis import (  # noqa: E402
    _center_crop,
    _edge_variance,
    NOISE_CROP_SIZE,
    NOISE_RESIDUAL_STDDEV_THRESHOLD,
    QUALITY_ANALYSIS_MAX_SIDE,
)

_CITY_DIR = Path(__file__).parent.parent / "city_organize_prototype" / "sample_photos"
_WORK_DIR = Path(__file__).parent / "_work"


def measure_noise_stddev(path: Path) -> float:
    with Image.open(path) as img:
        gray = img.convert("L")
        sample = _center_crop(gray, NOISE_CROP_SIZE)
        denoised = sample.filter(ImageFilter.MedianFilter(size=3))
        residual = ImageChops.difference(sample, denoised)
        return ImageStat.Stat(residual).stddev[0]


def measure_edge_variance(path: Path) -> float:
    with Image.open(path) as img:
        gray = img.convert("L")
        gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))
        return _edge_variance(gray)


def make_noisy_copy(src: Path, dest: Path, sigma: float) -> None:
    with Image.open(src) as img:
        rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    noise = np.random.default_rng(0).normal(0, sigma, rgb.shape)
    noisy = np.clip(rgb + noise, 0, 255).astype(np.uint8)
    Image.fromarray(noisy).save(dest)


def make_random_noise_image(dest: Path, size=(600, 400)) -> None:
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr).save(dest)


def main():
    if not denoise.is_available():
        print("NAFNet-SIDD 가중치가 없어서 실제 추론은 건너뜁니다 (사전점검 수치만 출력).")

    _WORK_DIR.mkdir(exist_ok=True)
    candidates: list[Path] = []

    city_photos = sorted(_CITY_DIR.glob("*.jpg")) if _CITY_DIR.exists() else []
    candidates.extend(city_photos)

    if city_photos:
        noisy_copy = _WORK_DIR / f"noisy_{city_photos[0].stem}.png"
        make_noisy_copy(city_photos[0], noisy_copy, sigma=15.0)
        candidates.append(noisy_copy)

    random_noise = _WORK_DIR / "random_noise.png"
    make_random_noise_image(random_noise)
    candidates.append(random_noise)

    with tempfile.TemporaryDirectory() as tmp:
        print(f"{'file':30s} {'noise_stddev':>14s} {'noisy?(>%.1f)' % NOISE_RESIDUAL_STDDEV_THRESHOLD:>16s} {'input_ev':>10s} {'output_ev':>10s} {'ratio':>8s}")
        for path in candidates:
            if not path.exists():
                print(f"{path.name:30s} (파일 없음, 건너뜀)")
                continue

            noise_stddev = measure_noise_stddev(path)
            is_noisy = noise_stddev > NOISE_RESIDUAL_STDDEV_THRESHOLD
            input_ev = measure_edge_variance(path)

            output_ev = None
            ratio = None
            if denoise.is_available():
                try:
                    out_path = denoise.denoise_image(str(path), tmp, suffix="test")
                    output_ev = measure_edge_variance(Path(out_path))
                    ratio = output_ev / input_ev if input_ev > 0 else float("inf")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {path.name} 추론 실패: {exc}")

            out_str = f"{output_ev:10.1f}" if output_ev is not None else " " * 10
            ratio_str = f"{ratio:8.2f}" if ratio is not None else " " * 8
            print(f"{path.name:30s} {noise_stddev:14.2f} {str(is_noisy):>16s} {input_ev:10.1f} {out_str} {ratio_str}")


if __name__ == "__main__":
    main()
