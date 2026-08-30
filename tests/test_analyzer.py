"""
core/analyzer.py 테스트

PRD 8장 "파일 상태 분류"의 각 케이스(정상/형식불일치/부분손상/손상/
이미지가 아닌 파일)를 실제로 만들어서 analyze_file()이 올바르게
분류하는지 확인한다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import pillow_heif

from core.analyzer import analyze_file
from models.file_info import FileStatus, RecoveryPossibility


def make_jpeg(path: Path, size=(20, 20)):
    Image.new("RGB", size, color="red").save(path, format="JPEG")


def make_heic(path: Path):
    img = Image.new("RGB", (20, 20), color="green")
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(path, quality=80)


def run():
    passed = 0
    failed = 0

    def check(label, condition, extra=""):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {label} {extra}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1) 정상 JPEG
        p = tmp / "ok.jpg"
        make_jpeg(p)
        info = analyze_file(p)
        check("정상 JPEG -> status=정상", info.status == FileStatus.NORMAL, info.summary())
        check("정상 JPEG -> readable=True", info.readable is True)
        check("정상 JPEG -> 해상도 인식", info.width == 20 and info.height == 20)
        check("정상 JPEG -> 복구불필요", info.recoverable == RecoveryPossibility.NOT_APPLICABLE)

        # 2) HEIC인데 .jpg로 위장 (PRD 9장 핵심 케이스)
        p = tmp / "IMG_1234.jpg"
        make_heic(p)
        info = analyze_file(p)
        check("HEIC(.jpg 위장) -> status=형식_불일치", info.status == FileStatus.MISMATCH, info.summary())
        check("HEIC(.jpg 위장) -> detected_format=HEIC", info.detected_format == "HEIC")
        check("HEIC(.jpg 위장) -> 복구가능", info.recoverable == RecoveryPossibility.RECOVERABLE)

        # 3) 완전히 손상된 파일 (JPEG 헤더는 있지만 나머지가 깨짐)
        p = tmp / "broken.jpg"
        good = tmp / "_tmp_good.jpg"
        make_jpeg(good, size=(200, 200))
        raw = good.read_bytes()
        # 헤더(시그니처)는 남기고 본문 대부분을 잘라내어 '부분 손상' 유도
        p.write_bytes(raw[:200])
        info = analyze_file(p)
        check(
            "잘린 JPEG -> status가 부분_손상 또는 손상",
            info.status in (FileStatus.PARTIAL_CORRUPTION, FileStatus.CORRUPTED),
            info.summary(),
        )

        # 4) 완전 빈 파일 (0바이트)
        p = tmp / "empty.jpg"
        p.write_bytes(b"")
        info = analyze_file(p)
        check("빈 파일 -> status=이미지가_아닌_파일", info.status == FileStatus.NOT_AN_IMAGE, info.summary())

        # 5) 텍스트를 .png로 위장 (UTF-8)
        p = tmp / "note.png"
        p.write_text("사진이 아니라 메모입니다." * 5, encoding="utf-8")
        info = analyze_file(p)
        check("텍스트(.png 위장, UTF-8) -> status=이미지가_아닌_파일", info.status == FileStatus.NOT_AN_IMAGE, info.summary())

        # 5-1) 텍스트를 .png로 위장 (Windows 한글 인코딩 cp949) - 실제 버그 재현 케이스
        p = tmp / "note_cp949.png"
        p.write_bytes(("사진이 아니라 메모입니다." * 5).encode("cp949"))
        info = analyze_file(p)
        check("텍스트(.png 위장, CP949) -> status=이미지가_아닌_파일", info.status == FileStatus.NOT_AN_IMAGE, info.summary())

        # 6) 지원하지 않는 확장자 (실제로도 그 형식)
        p = tmp / "note.txt"
        p.write_text("아무 텍스트 파일", encoding="utf-8")
        info = analyze_file(p)
        check("txt 파일 -> status=이미지가_아닌_파일/지원안함", info.status in (FileStatus.NOT_AN_IMAGE, FileStatus.UNSUPPORTED), info.summary())

        # 7) PRD 37.6 "추가 포맷 지원": GIF/TIFF/BMP가 더 이상 UNSUPPORTED가 아니라
        # 정상적으로 분석되는지 확인 (예전엔 core/analyzer.py의 하드코딩된 지원 목록에서 빠져있었음)
        p = tmp / "normal.gif"
        Image.new("RGB", (20, 20), color="yellow").save(p, format="GIF")
        info = analyze_file(p)
        check("정상 GIF -> status=정상", info.status == FileStatus.NORMAL, info.summary())

        p = tmp / "normal.bmp"
        Image.new("RGB", (20, 20), color="orange").save(p, format="BMP")
        info = analyze_file(p)
        check("정상 BMP -> status=정상", info.status == FileStatus.NORMAL, info.summary())

        p = tmp / "normal.tiff"
        Image.new("RGB", (20, 20), color="purple").save(p, format="TIFF")
        info = analyze_file(p)
        check("정상 TIFF -> status=정상", info.status == FileStatus.NORMAL, info.summary())

        # 7-1) GIF인데 .jpg로 위장 -> 형식 불일치로 잡혀야 함 (WEBP/HEIC와 같은 패턴)
        p = tmp / "IMG_9999.jpg"
        Image.new("RGB", (20, 20), color="yellow").save(p, format="GIF")
        info = analyze_file(p)
        check("GIF(.jpg 위장) -> status=형식_불일치", info.status == FileStatus.MISMATCH, info.summary())
        check("GIF(.jpg 위장) -> 복구가능", info.recoverable == RecoveryPossibility.RECOVERABLE)

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
