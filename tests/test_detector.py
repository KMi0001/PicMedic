"""
core/detector.py 테스트

PRD 34장 "품질 검증" 테스트 데이터셋 항목 중
'정상', '확장자 오류', '손상' 케이스를 실제로 만들어 검증한다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import pillow_heif

from core import detector


def make_jpeg(path: Path):
    Image.new("RGB", (20, 20), color="red").save(path, format="JPEG")


def make_png(path: Path):
    Image.new("RGB", (20, 20), color="blue").save(path, format="PNG")


def make_heic(path: Path):
    img = Image.new("RGB", (20, 20), color="green")
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(path, quality=80)


def make_gif(path: Path):
    Image.new("RGB", (20, 20), color="yellow").save(path, format="GIF")


def make_bmp(path: Path):
    Image.new("RGB", (20, 20), color="orange").save(path, format="BMP")


def make_tiff(path: Path):
    Image.new("RGB", (20, 20), color="purple").save(path, format="TIFF")


def run():
    passed = 0
    failed = 0

    def check(label, condition):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1) 정상 JPEG
        jpg_path = tmp / "normal.jpg"
        make_jpeg(jpg_path)
        check("정상 JPEG -> JPEG로 탐지", detector.detect_format(jpg_path) == "JPEG")

        # 2) 정상 PNG
        png_path = tmp / "normal.png"
        make_png(png_path)
        check("정상 PNG -> PNG로 탐지", detector.detect_format(png_path) == "PNG")

        # 3) 정상 HEIC
        heic_path = tmp / "normal.heic"
        make_heic(heic_path)
        check("정상 HEIC -> HEIC로 탐지", detector.detect_format(heic_path) == "HEIC")

        # 4) HEIC인데 확장자가 .jpg인 케이스 (PRD 9장 핵심 시나리오)
        fake_jpg_path = tmp / "IMG_1234.jpg"
        make_heic(fake_jpg_path)
        detected = detector.detect_format(fake_jpg_path)
        check("HEIC를 .jpg로 위장 -> 실제 형식은 HEIC로 탐지", detected == "HEIC")
        check(
            "확장자(.jpg)와 실제형식(HEIC) 불일치로 판정",
            not detector.extension_matches_format(".jpg", detected),
        )

        # 5) 완전히 빈 파일 (손상 시나리오)
        empty_path = tmp / "empty.jpg"
        empty_path.write_bytes(b"")
        check("빈 파일 -> 형식 탐지 실패(None)", detector.detect_format(empty_path) is None)

        # 6) 텍스트 파일을 .png로 위장 (이미지가 아닌 파일 시나리오)
        text_path = tmp / "not_an_image.png"
        text_path.write_text("이것은 이미지가 아닙니다.", encoding="utf-8")
        check("텍스트 파일 -> 형식 탐지 실패(None)", detector.detect_format(text_path) is None)

        # 6-1) PRD 37.6 "추가 포맷 지원": GIF/TIFF/BMP 시그니처 탐지 및 확장자 일치 확인
        gif_path = tmp / "normal.gif"
        make_gif(gif_path)
        check("정상 GIF -> GIF로 탐지", detector.detect_format(gif_path) == "GIF")
        check("'.gif' 확장자는 GIF와 일치", detector.extension_matches_format(".gif", "GIF"))

        bmp_path = tmp / "normal.bmp"
        make_bmp(bmp_path)
        check("정상 BMP -> BMP로 탐지", detector.detect_format(bmp_path) == "BMP")
        check("'.bmp' 확장자는 BMP와 일치", detector.extension_matches_format(".bmp", "BMP"))

        tiff_path = tmp / "normal.tiff"
        make_tiff(tiff_path)
        check("정상 TIFF -> TIFF로 탐지", detector.detect_format(tiff_path) == "TIFF")
        check("'.tiff' 확장자는 TIFF와 일치", detector.extension_matches_format(".tiff", "TIFF"))

        # 7) 지원 확장자 판별
        check("'.jpg'는 MVP 지원 확장자", detector.is_mvp_supported_extension(".jpg"))
        check("'.webp'는 지원 확장자(복구 변환 대상으로 쓰임)", detector.is_mvp_supported_extension(".webp"))
        # PRD 37.6 "추가 포맷 지원": GIF/TIFF/BMP도 WEBP와 같은 패턴으로 지원 확장자에 포함됨
        check("'.gif'는 지원 확장자(추가 포맷 지원)", detector.is_mvp_supported_extension(".gif"))
        check("'.tiff'는 지원 확장자(추가 포맷 지원)", detector.is_mvp_supported_extension(".tiff"))
        check("'.bmp'는 지원 확장자(추가 포맷 지원)", detector.is_mvp_supported_extension(".bmp"))
        check("'.avif'는 아직 지원 확장자 아님", not detector.is_mvp_supported_extension(".avif"))

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
