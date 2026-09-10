"""
tests/test_quality_diagnosis.py

core/quality_diagnosis.py 검증. assess_quality_issues()·is_low_resolution()는
Pillow 통계 기반 순수 함수라 항상 실행되고, diagnose_photo()의 추천 우선순위
로직(블러+얼굴 > 블러 > 노이즈 > 저해상도 > 없음)도 검증한다 — 테스트 이미지는
얼굴로 오인될 여지가 없는 단색/그라디언트라 얼굴 탐지 자산이 있든 없든 결과가
일정하다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

import numpy as np
from PIL import Image, ImageFilter

from core import quality_diagnosis as qd


def _save(img: Image.Image, path: Path):
    img.save(path, format="PNG")


def _sharp_image(size=(600, 600)) -> Image.Image:
    """또렷한 경계가 많은 체크보드 — 블러/저대비 추정 둘 다 안 걸려야 한다."""
    arr = np.zeros((size[1], size[0]), dtype=np.uint8)
    step = 20
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2 == 0:
                arr[y : y + step, x : x + step] = 230
            else:
                arr[y : y + step, x : x + step] = 20
    return Image.fromarray(arr, mode="L").convert("RGB")


def test_quality_diagnosis():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        sharp_path = tmp / "sharp.png"
        _save(_sharp_image(), sharp_path)
        sharp_issues = qd.assess_quality_issues(sharp_path)
        check("또렷한 체크보드는 블러로 오판되지 않음", "블러 추정" not in sharp_issues, sharp_issues)
        check("또렷한 체크보드는 저대비로 오판되지 않음", "저대비 추정" not in sharp_issues, sharp_issues)

        blurry_path = tmp / "blurry.png"
        _save(_sharp_image().filter(ImageFilter.GaussianBlur(radius=8)), blurry_path)
        blurry_issues = qd.assess_quality_issues(blurry_path)
        check("강하게 블러 처리한 사진은 블러 추정이 걸림", "블러 추정" in blurry_issues, blurry_issues)

        dark_path = tmp / "dark.png"
        _save(Image.new("RGB", (400, 400), (10, 10, 10)), dark_path)
        dark_issues = qd.assess_quality_issues(dark_path)
        check("어두운 단색 사진은 노출 부족 추정이 걸림", "노출 부족 추정" in dark_issues, dark_issues)

        bright_path = tmp / "bright.png"
        _save(Image.new("RGB", (400, 400), (250, 250, 250)), bright_path)
        bright_issues = qd.assess_quality_issues(bright_path)
        check("밝은 단색 사진은 노출 과다 추정이 걸림", "노출 과다 추정" in bright_issues, bright_issues)

        noisy_path = tmp / "noisy.png"
        base = np.full((400, 400), 128, dtype=np.float64)
        noise = np.random.RandomState(0).normal(0, 30, base.shape)
        noisy_arr = np.clip(base + noise, 0, 255).astype(np.uint8)
        _save(Image.fromarray(noisy_arr, mode="L").convert("RGB"), noisy_path)
        noisy_issues = qd.assess_quality_issues(noisy_path)
        check("강한 노이즈를 주입한 사진은 노이즈 추정이 걸림", "노이즈 추정" in noisy_issues, noisy_issues)

        check("저해상도 판단: 100x100은 저해상도", qd.is_low_resolution(100, 100))
        check("저해상도 판단: 4000x3000은 저해상도 아님", not qd.is_low_resolution(4000, 3000))
        check("저해상도 판단: width/height 없으면 False", not qd.is_low_resolution(None, None))

        # --- diagnose_photo() 추천 우선순위: 블러 > 노이즈 > 저해상도 > 없음.
        # (블러+얼굴 조합은 얼굴 탐지 자산이 있어야만 검증 가능해 스킵 대상 —
        # 여기 이미지들엔 얼굴로 오인될 요소가 없어 자산 유무와 무관하게 일정함.)
        blur_diag = qd.diagnose_photo(str(blurry_path))
        check("진단: 블러 사진은 디블러를 추천", blur_diag.recommended_action == "디블러", blur_diag.recommended_action)

        noise_diag = qd.diagnose_photo(str(noisy_path))
        check(
            "진단: 노이즈 사진(블러 없음)은 디노이즈를 추천",
            noise_diag.recommended_action == "디노이즈",
            noise_diag.recommended_action,
        )

        lowres_diag = qd.diagnose_photo(str(sharp_path), width=100, height=100)
        check(
            "진단: 문제 없지만 저해상도면 화질 개선을 추천",
            lowres_diag.recommended_action == "화질 개선",
            lowres_diag.recommended_action,
        )

        clean_diag = qd.diagnose_photo(str(sharp_path), width=4000, height=3000)
        check(
            "진단: 문제 없고 고해상도면 추천 없음",
            clean_diag.recommended_action is None,
            clean_diag.recommended_action,
        )

        # --- 취소 지원 ---
        try:
            qd.diagnose_photo(str(sharp_path), should_cancel=lambda: True)
            check("진단: 취소 요청 시 DiagnosisCancelled 발생", False)
        except qd.DiagnosisCancelled:
            check("진단: 취소 요청 시 DiagnosisCancelled 발생", True)

        # --- progress_callback 호출 형태 ---
        calls = []
        qd.diagnose_photo(str(sharp_path), progress_callback=lambda step, total, label: calls.append((step, total)))
        check(
            "진단: progress_callback이 (현재단계,전체단계) 형태로 호출됨, 마지막은 완료",
            len(calls) > 0 and calls[-1][0] == calls[-1][1],
            calls,
        )


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_quality_diagnosis()
    print("OK")
