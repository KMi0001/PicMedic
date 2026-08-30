import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import pillow_heif

from core.analyzer import analyze_file
from core.converter import RecoveryMode, recover_batch, recover_file


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
        outcome7 = recover_file(info_png, RecoveryMode.CONVERT, output_dir, target_format="AVIF")
        check("지원하지 않는 변환 형식은 실패 처리됨", not outcome7.success)

        # 8) 부분 손상 파일 변환 — PRD_MVP우선순위.md '남은 갭 #4' 회귀 테스트.
        # analyzer는 잘린 이미지도 끝까지 읽어서 '부분_손상/부분_복구_가능'으로 판정하는데,
        # 예전엔 converter가 이 모드를 안 켜서 실제 변환은 항상 'image file is truncated'로 실패했다.
        good_jpg = tmp / "_good_for_truncation.jpg"
        Image.new("RGB", (300, 300), color="red").save(good_jpg, format="JPEG", quality=90)
        raw = good_jpg.read_bytes()
        partial_jpg = tmp / "PARTIAL_BROKEN.jpg"
        partial_jpg.write_bytes(raw[: int(len(raw) * 0.7)])  # 헤더는 남기고 본문 뒷부분만 잘라냄
        info_partial = analyze_file(partial_jpg)
        check(
            "사전 조건: 잘린 JPEG가 부분_손상/부분_복구_가능으로 판정됨",
            info_partial.status.value == "부분_손상",
            info_partial.summary(),
        )
        outcome8 = recover_file(info_partial, RecoveryMode.CONVERT, output_dir, target_format="JPEG")
        check("부분 손상 파일도 변환 시도가 실패하지 않음", outcome8.success, outcome8.error_message or "")

        # 9~12) 예외 메시지 PRD 23장 문구 정합화 — PRD_MVP우선순위.md '남은 갭 #2' 회귀 테스트.
        locked_exc = OSError("The process cannot access the file because it is being used by another process")
        locked_exc.winerror = 32
        with patch("shutil.copy2", side_effect=locked_exc):
            outcome9 = recover_file(info, RecoveryMode.RESTORE_EXTENSION, output_dir)
        check(
            "파일 잠금(23.3) 시 PRD 문구로 안내됨",
            outcome9.error_message == "다른 프로그램에서 사용 중인 파일입니다.",
            outcome9.error_message,
        )
        check("파일 잠금은 배치를 중단시키지 않음", not outcome9.abort_batch)

        with patch("shutil.copy2", side_effect=PermissionError("Permission denied")):
            outcome10 = recover_file(info, RecoveryMode.RESTORE_EXTENSION, output_dir)
        check(
            "권한 없음(23.1) 시 PRD 문구로 안내됨",
            outcome10.error_message == "이 파일에 접근할 수 없습니다.",
            outcome10.error_message,
        )

        disk_full_exc = OSError("There is not enough space on the disk")
        disk_full_exc.winerror = 112
        with patch("shutil.copy2", side_effect=disk_full_exc):
            outcome11 = recover_file(info, RecoveryMode.RESTORE_EXTENSION, output_dir)
        check(
            "저장 공간 부족(23.5) 시 PRD 문구로 안내됨",
            outcome11.error_message == "복구 파일을 저장할 공간이 부족합니다.",
            outcome11.error_message,
        )
        check("저장 공간 부족은 배치 중단 신호를 켬", outcome11.abort_batch)

        with patch("shutil.copy2", side_effect=disk_full_exc):
            outcomes12 = recover_batch([info, info, info], RecoveryMode.RESTORE_EXTENSION, output_dir)
        check(
            "저장 공간 부족 시 배치가 첫 실패 이후 중단됨(나머지 파일 건너뜀)",
            len(outcomes12) == 1,
            f"실제 처리 개수={len(outcomes12)}",
        )

        # 13~15) PRD 37.6 "추가 포맷 지원": GIF/TIFF/BMP도 WEBP와 같은 패턴으로 변환 가능해야 한다.
        for fmt, ext in (("GIF", ".gif"), ("TIFF", ".tiff"), ("BMP", ".bmp")):
            outcome = recover_file(info, RecoveryMode.CONVERT, output_dir, target_format=fmt)
            check(f"{fmt} 변환 성공", outcome.success, outcome.error_message or "")
            check(f"{fmt} 변환 재검증 통과", outcome.verified)
            check(f"{fmt} 변환 결과 파일이 {ext}로 끝남", outcome.output_path.endswith(ext))

        # 16) quality 파라미터가 recover_file/recover_batch까지 실제로 전달되는지 확인
        # (예전엔 이 파라미터 자체가 없어서 항상 내부 기본값 90으로 고정이었음)
        low_q = recover_file(info, RecoveryMode.CONVERT, output_dir, target_format="JPEG", quality=20)
        high_q = recover_file(info, RecoveryMode.CONVERT, output_dir, target_format="JPEG", quality=95)
        check("낮은 quality 변환 성공", low_q.success, low_q.error_message or "")
        check("높은 quality 변환 성공", high_q.success, high_q.error_message or "")
        check(
            "낮은 quality 결과가 높은 quality 결과보다 파일 크기가 작음(=quality가 실제로 적용됨)",
            Path(low_q.output_path).stat().st_size < Path(high_q.output_path).stat().st_size,
            f"low={Path(low_q.output_path).stat().st_size}B high={Path(high_q.output_path).stat().st_size}B",
        )

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
