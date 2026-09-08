"""
tests/test_ai_restoration.py

core/quality_enhancer.py·core/face_restorer.py·core/deblur.py·core/denoise.py
공통 검증: is_available()/estimate 계산은 자산(수백MB 모델 파일) 없이도 항상
돌지만, 실제 실행(enhance_quality 등)은 자산이 있어야만 하므로 없으면
tests/test_scanner.py의 심볼릭 링크 SKIP과 같은 방식으로 건너뛴다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageFilter

from core import deblur, denoise, face_restorer, quality_enhancer


def _make_test_photo(path: Path, size=(300, 200)):
    """가짜 사진 — 실제 얼굴/풍경은 아니지만 디코딩 가능한 사진 파일이면
    충분한 테스트(모델 성공/실패 자체가 아니라 파이프라인 동작을 본다)."""
    img = Image.new("RGB", size, color=(120, 140, 160))
    img = img.filter(ImageFilter.GaussianBlur(radius=2))
    img.save(path, format="PNG")


def run():
    passed = failed = skipped = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

    def skip(label):
        nonlocal skipped
        skipped += 1
        print(f"[SKIP] {label}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        photo_path = tmp / "test.png"
        _make_test_photo(photo_path)
        output_dir = tmp / "Enhanced"

        # --- estimate 계산은 자산 없이도 항상 동작해야 한다(순수 함수) ---
        check(
            "quality_enhancer.estimate_seconds는 해상도가 클수록 더 크다",
            quality_enhancer.estimate_seconds(4000, 3000) > quality_enhancer.estimate_seconds(800, 600),
        )
        check(
            "deblur.estimate_seconds는 해상도가 클수록 더 크다",
            deblur.estimate_seconds(4000, 3000) > deblur.estimate_seconds(800, 600),
        )
        check(
            "denoise.estimate_seconds는 해상도가 클수록 더 크다",
            denoise.estimate_seconds(4000, 3000) > denoise.estimate_seconds(800, 600),
        )
        low, high = face_restorer.estimate_seconds_range()
        check("face_restorer.estimate_seconds_range는 (낮, 높음) 순서", low <= high)

        # --- 실제 모델 실행(자산이 받아져 있어야 함 — 없으면 스킵) ---
        if quality_enhancer.is_available():
            result_path = quality_enhancer.enhance_quality(str(photo_path), str(output_dir))
            check("enhance_quality: 결과 파일 생성됨", Path(result_path).exists())
            check("enhance_quality: 원본 파일은 그대로 남음", photo_path.exists())
        else:
            skip("enhance_quality 실제 실행 (assets/realesrgan/ 없음 — scripts/fetch_realesrgan_assets.py 필요)")

        if deblur.is_available():
            # 테스트용 사진은 실제 모션 블러가 아니라 단색+가우시안 블러라
            # NAFNet-GoPro 입장에선 도메인 밖 입력에 가깝다 — 안전장치
            # (DeblurNotRecommendedError/DeblurResultUnstableError)가 걸러내는
            # 것도 "실행 자체가 죽지 않음"이라는 이 테스트의 목적엔 정상 결과다
            # (face_restorer의 NoFaceFoundError 처리와 같은 이유).
            try:
                result_path = deblur.deblur_image(str(photo_path), str(output_dir))
                check("deblur_image: 결과 파일 생성됨", Path(result_path).exists())
            except (deblur.DeblurNotRecommendedError, deblur.DeblurResultUnstableError):
                check("deblur_image: 안전장치가 도메인 밖 입력을 정상적으로 걸러냄", True)
            check("deblur_image: 원본 파일은 그대로 남음", photo_path.exists())
        else:
            skip("deblur_image 실제 실행 (assets/deblur/ 없음 — scripts/fetch_deblur_assets.py 필요)")

        if denoise.is_available():
            result_path = denoise.denoise_image(str(photo_path), str(output_dir))
            check("denoise_image: 결과 파일 생성됨", Path(result_path).exists())
            check("denoise_image: 원본 파일은 그대로 남음", photo_path.exists())
        else:
            skip("denoise_image 실제 실행 (assets/denoise/ 없음 — scripts/fetch_denoise_assets.py 필요)")

        if face_restorer.is_available():
            # 테스트용 사진엔 진짜 얼굴이 없어 NoFaceFoundError가 정상 결과다 —
            # "얼굴 없음"과 "실행 자체가 죽지 않음"만 확인한다.
            try:
                face_restorer.restore_face(str(photo_path), str(output_dir))
                check("restore_face: 예외 없이 완료됨", True)
            except face_restorer.NoFaceFoundError:
                check("restore_face: 얼굴 없는 사진은 NoFaceFoundError로 정상 처리", True)
            check("restore_face: 원본 파일은 그대로 남음", photo_path.exists())
        else:
            skip("restore_face 실제 실행 (assets/face_restore/ 없음 — scripts/fetch_face_restore_assets.py 필요)")

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패 ({skipped}개 스킵)")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
