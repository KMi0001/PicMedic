import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import pillow_heif

from core.analyzer import analyze_file
from core.converter import RecoveryMode, recover_file


def make_heic(path: Path):
    img = Image.new("RGB", (30, 30), color="purple")
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(path, quality=80)


def run():
    passed = failed = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        output_dir = tmp / "Recovered"

        fake_jpg = tmp / "IMG_1234.jpg"
        make_heic(fake_jpg)
        info = analyze_file(fake_jpg)
        check("사전 조건: HEIC(.jpg 위장) 형식_불일치 감지됨", info.status.value == "형식_불일치")

        # 1) 확장자 복원
        outcome = recover_file(info, RecoveryMode.RESTORE_EXTENSION, output_dir)
        check("확장자 복원 성공", outcome.success, outcome.error_message or "")
        check("확장자 복원 재검증 통과", outcome.verified)
        check("확장자 복원 결과 파일 .heic로 끝남", outcome.output_path.endswith(".heic"))
        check("원본 파일이 그대로 남아있음", fake_jpg.exists())

        # 2) JPEG 변환 (기본 형식)
        outcome2 = recover_file(info, RecoveryMode.CONVERT, output_dir, target_format="JPEG")
        check("JPEG 변환 성공", outcome2.success, outcome2.error_message or "")
        check("JPEG 변환 재검증 통과", outcome2.verified)
        check("JPEG 변환 결과 파일 .jpg로 끝남", outcome2.output_path.endswith(".jpg"))

        # 3) 같은 파일 다시 복구 시도 -> 파일명 충돌 회피 확인
        outcome3 = recover_file(info, RecoveryMode.RESTORE_EXTENSION, output_dir)
        check(
            "동일 파일 재복구 시 파일명 충돌 회피(_2)",
            outcome3.output_path != outcome.output_path and outcome3.success,
            outcome3.output_path,
        )

        # 4) PNG로 변환 (알파 채널 유지 확인)
        rgba_png = tmp / "TRANSPARENT.png"
        Image.new("RGBA", (20, 20), (255, 0, 0, 128)).save(rgba_png, format="PNG")
        info_png = analyze_file(rgba_png)
        outcome4 = recover_file(info_png, RecoveryMode.CONVERT, output_dir, target_format="PNG")
        check("PNG 변환 성공", outcome4.success, outcome4.error_message or "")
        check("PNG 변환 재검증 통과", outcome4.verified)
        check("PNG 변환 결과 파일 .png로 끝남", outcome4.output_path.endswith(".png"))
        with Image.open(outcome4.output_path) as saved:
            check("PNG 변환 시 알파 채널 유지됨", saved.mode in ("RGBA", "LA"), saved.mode)

        # 5) WEBP로 변환
        outcome5 = recover_file(info_png, RecoveryMode.CONVERT, output_dir, target_format="WEBP")
        check("WEBP 변환 성공", outcome5.success, outcome5.error_message or "")
        check("WEBP 변환 재검증 통과", outcome5.verified)
        check("WEBP 변환 결과 파일 .webp로 끝남", outcome5.output_path.endswith(".webp"))

        # 6) JPEG로 변환 시 알파 채널이 없는 형식이므로 RGB로 눌러야 함
        outcome6 = recover_file(info_png, RecoveryMode.CONVERT, output_dir, target_format="JPEG")
        check("알파 있는 PNG -> JPEG 변환도 성공", outcome6.success, outcome6.error_message or "")
        with Image.open(outcome6.output_path) as saved:
            check("JPEG 변환 시 알파 채널 제거됨(RGB)", saved.mode == "RGB", saved.mode)

        # 7) 지원하지 않는 변환 형식 요청 시 명확한 에러
        outcome7 = recover_file(info_png, RecoveryMode.CONVERT, output_dir, target_format="GIF")
        check("지원하지 않는 변환 형식은 실패 처리됨", not outcome7.success)

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
