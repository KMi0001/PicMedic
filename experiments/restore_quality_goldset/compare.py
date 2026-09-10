"""
experiments/restore_quality_goldset/compare.py

RESTORATION_QUALITY_PLAN.md P1 "골드셋 + Before/After 시각 비교 리포트"의
시작 버전. 자동 판정이 아니라 사람이 눈으로 훑어보고 "이 정도면 팔 만하다"를
판단할 근거 자료를 만드는 게 목적 — experiments/deblur_safety_prototype/measure.py
처럼 core/*.py는 건드리지 않는 1회성 스크립트.

지금은 "진짜 골드셋"이 아니라 이미 저장소에 있던 샘플을 재사용한 출발점이다:
- experiments/restore_prototype/test_images/old_blurry_portrait.jpg — 실제 손떨림
  있는 인물 사진 (디블러/얼굴복원 both 적용 가능).
- experiments/city_organize_prototype/sample_photos/*.jpg — 도시별 정리 프로토타입용
  풍경 사진. 실측해보니(2026-09-11) 전부 동일한 합성 이미지라 노이즈/블러가 전혀
  없다 — 디노이즈/화질개선의 "정상 입력에서 결과가 좋은지"를 보여주는 용도로는
  약하다. 실제 저조도 노이즈 사진·다양한 각도/크기의 인물 사진은 아직 없다
  (RESTORATION_QUALITY_PLAN.md 1-5, 5의 골드셋 항목 참고) — 저작권 문제 없는
  실사진을 구해서 이 폴더에 추가하고 CANDIDATES에 등록할 것.

실행: python experiments/restore_quality_goldset/compare.py
결과: experiments/restore_quality_goldset/_output/ 아래 "<기능>_<파일명>.png"로
      원본|결과 나란히 붙인 비교 이미지 저장 (자산 없는 기능은 조용히 건너뜀).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from core import deblur, denoise, face_restorer, quality_enhancer  # noqa: E402

_TEST_IMAGES_DIR = Path(__file__).parent.parent / "restore_prototype" / "test_images"
_CITY_DIR = Path(__file__).parent.parent / "city_organize_prototype" / "sample_photos"
_OUTPUT_DIR = Path(__file__).parent / "_output"

_LABEL_HEIGHT = 24


def _make_side_by_side(before_path: Path, after_path: Path, out_path: Path) -> None:
    with Image.open(before_path) as before, Image.open(after_path) as after:
        before = before.convert("RGB")
        after = after.convert("RGB")
        h = max(before.height, after.height)
        w = before.width + after.width
        canvas = Image.new("RGB", (w, h + _LABEL_HEIGHT), color=(30, 30, 30))
        canvas.paste(before, (0, _LABEL_HEIGHT))
        canvas.paste(after, (before.width, _LABEL_HEIGHT))
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 4), "원본", fill=(255, 255, 255))
        draw.text((before.width + 8, 4), "결과", fill=(255, 255, 255))
        canvas.save(out_path)


def _run_case(label: str, fn, src: Path, tmp_dir: Path) -> None:
    out_name = f"{label}_{src.stem}.png"
    try:
        result_path = fn(str(src), str(tmp_dir))
    except Exception as exc:  # noqa: BLE001 - 골드셋 실행은 실패도 "결과"라 기록만 하고 계속
        print(f"  ! {out_name}: {type(exc).__name__}: {exc}")
        return
    _OUTPUT_DIR.mkdir(exist_ok=True)
    _make_side_by_side(src, Path(result_path), _OUTPUT_DIR / out_name)
    print(f"  ok {out_name}")


def main():
    blurry_portrait = _TEST_IMAGES_DIR / "old_blurry_portrait.jpg"
    city_photos = sorted(_CITY_DIR.glob("*.jpg")) if _CITY_DIR.exists() else []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        if deblur.is_available() and blurry_portrait.exists():
            print("deblur:")
            _run_case("deblur", deblur.deblur_image, blurry_portrait, tmp_dir)
        else:
            print("deblur: 건너뜀 (자산 또는 샘플 없음)")

        if denoise.is_available() and city_photos:
            print("denoise:")
            _run_case("denoise", denoise.denoise_image, city_photos[0], tmp_dir)
        else:
            print("denoise: 건너뜀 (자산 또는 샘플 없음 — 실제 노이즈 있는 사진 필요, 알려진 한계 참고)")

        if face_restorer.is_available() and blurry_portrait.exists():
            print("face_restorer:")
            _run_case("face_restore", face_restorer.restore_face, blurry_portrait, tmp_dir)
        else:
            print("face_restorer: 건너뜀 (자산 또는 샘플 없음)")

        if quality_enhancer.is_available() and city_photos:
            print("quality_enhancer:")
            _run_case("upscale", quality_enhancer.enhance_quality, city_photos[0], tmp_dir)
        else:
            print("quality_enhancer: 건너뜀 (자산 또는 샘플 없음)")

    print(f"\n결과 저장 위치: {_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
