"""
experiments/deblur_safety_prototype/measure.py

디블러 사전/사후 안전장치용 임계값을 실측으로 정하기 위한 1회성 스크립트.
core/deblur.py에 바로 손대지 않고, 기존 프로토타입 테스트 이미지들로
"edge variance"(core/quality_diagnosis._edge_variance와 동일한 공식)를
원본/NAFNet 출력 양쪽에 찍어본다.

가설: 이미 선명한 사진(quality_diagnosis 기준 "블러 추정" 아님)에 NAFNet을
돌리면 출력의 edge variance가 원본 대비 비정상적으로 폭증한다(사용자가 보고한
컬러 노이즈 현상). 반대로 실제 블러 사진 → 좋은 결과(out_nafnet.png, 이미
검증된 정상 케이스)는 edge variance가 늘어나긴 해도 폭증까지는 안 갈 것.

실행: python experiments/deblur_safety_prototype/measure.py
(프로젝트 루트에서, PicMedic venv 활성화 후)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from PIL import Image  # noqa: E402

from core import deblur  # noqa: E402
from core.quality_diagnosis import _edge_variance, BLUR_EDGE_VARIANCE_THRESHOLD, QUALITY_ANALYSIS_MAX_SIDE  # noqa: E402

_TEST_DIR = Path(__file__).parent.parent / "restore_prototype" / "test_images"
_CITY_DIR = Path(__file__).parent.parent / "city_organize_prototype" / "sample_photos"

CANDIDATES = [
    _TEST_DIR / "old_blurry_portrait.jpg",   # 실제로 블러 있는 사진 (사전점검: 통과해야 함)
    _TEST_DIR / "out_nafnet.png",            # 위 사진의 "정상" NAFNet 결과 (이미 검증됨 - 오탐 없어야 함)
    _CITY_DIR / "busan.jpg",
    _CITY_DIR / "jeju.jpg",
    _CITY_DIR / "newyork.jpg",
    _CITY_DIR / "paris.jpg",
    _CITY_DIR / "seoul.jpg",
    _CITY_DIR / "tokyo.jpg",
]


def measure_edge_variance(path: Path) -> float:
    with Image.open(path) as img:
        gray = img.convert("L")
        gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))
        return _edge_variance(gray)


def main():
    if not deblur.is_available():
        print("NAFNet 가중치가 없어서 실제 추론은 건너뜁니다 (사전점검 수치만 출력).")

    with tempfile.TemporaryDirectory() as tmp:
        print(f"{'file':35s} {'input_edge_var':>16s} {'blur_flag(<%.0f)' % BLUR_EDGE_VARIANCE_THRESHOLD:>18s} {'output_edge_var':>16s} {'ratio':>8s}")
        for path in CANDIDATES:
            if not path.exists():
                print(f"{path.name:35s} (파일 없음, 건너뜀)")
                continue

            input_ev = measure_edge_variance(path)
            is_blurry = input_ev < BLUR_EDGE_VARIANCE_THRESHOLD

            output_ev = None
            ratio = None
            if deblur.is_available() and path.suffix.lower() != ".png":
                # out_nafnet.png는 이미 결과물이라 다시 돌리지 않고, 원본류만 추론
                try:
                    out_path = deblur.deblur_image(str(path), tmp, suffix="test")
                    output_ev = measure_edge_variance(Path(out_path))
                    ratio = output_ev / input_ev if input_ev > 0 else float("inf")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {path.name} 추론 실패: {exc}")

            out_str = f"{output_ev:16.1f}" if output_ev is not None else " " * 16
            ratio_str = f"{ratio:8.2f}" if ratio is not None else " " * 8
            print(f"{path.name:35s} {input_ev:16.1f} {str(is_blurry):>18s} {out_str} {ratio_str}")

        # out_nafnet.png 자체의 edge variance도 참고용으로 (이미 만들어진 정상 결과물)
        pre_made = _TEST_DIR / "out_nafnet.png"
        if pre_made.exists():
            ev = measure_edge_variance(pre_made)
            print(f"\n(참고) 이미 검증된 정상 NAFNet 결과물 out_nafnet.png 자체 edge_var = {ev:.1f}")


if __name__ == "__main__":
    main()
