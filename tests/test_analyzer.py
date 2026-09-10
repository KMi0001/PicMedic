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

from tests.helpers import check

from PIL import Image, ImageFile
import pillow_heif

from core.analyzer import analyze_file, decode_mode
from models.file_info import FileStatus, RecoveryPossibility


def make_jpeg(path: Path, size=(20, 20)):
    Image.new("RGB", size, color="red").save(path, format="JPEG")


def make_heic(path: Path):
    img = Image.new("RGB", (20, 20), color="green")
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(path, quality=80)


def test_analyzer():
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

        # 8) LOAD_TRUNCATED_IMAGES 오염 방지 (2026-09-11 리뷰에서 발견한 버그)
        #
        # 이 플래그는 Pillow 프로세스 전역이라, 다른 세션 창이 복구(형식 변환)를
        # 도는 동안엔 True로 켜져 있다. 예전 코드는 _try_decode 1차 시도가 그
        # 값을 그대로 물려받아서, 잘린 파일이 아무 문제 없이 읽히고 "정상"으로
        # 판정됐다 — 진단 결과가 옆 창의 작업 타이밍에 따라 달라졌다는 뜻이다.
        # 아래는 그 상황(다른 스레드가 켜둔 상태)을 그대로 재현한다.
        #
        # 절단 비율이 중요하다: 60%는 "손상 허용 모드에서는 읽히고 정상 모드에서는
        # 실패하는" 구간이라 부분_손상이 나온다. 이 구간이어야 옛 코드가 실제로
        # 정상으로 오판했다(실측 확인 — 200바이트만 남기면 양쪽 모드 다 실패해서
        # 그냥 손상이 나오고, 그러면 이 테스트가 버그를 못 잡는다).
        truncated = tmp / "truncated_while_converting.jpg"
        truncated.write_bytes(raw[: int(len(raw) * 0.6)])  # 위 3)에서 만든 정상 200x200 JPEG

        baseline = analyze_file(truncated).status
        check(
            "60% 절단 JPEG은 부분_손상으로 판정된다(아래 오염 테스트의 전제)",
            baseline == FileStatus.PARTIAL_CORRUPTION,
            baseline.value,
        )
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            polluted = analyze_file(truncated).status
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
        check(
            "다른 작업이 LOAD_TRUNCATED_IMAGES를 켜둬도 잘린 파일이 '정상'으로 안 바뀜",
            polluted == baseline and polluted != FileStatus.NORMAL,
            f"평소={baseline.value} / 켜둔 상태={polluted.value}",
        )
        check(
            "analyze_file은 LOAD_TRUNCATED_IMAGES를 원래 값으로 되돌려 놓는다",
            ImageFile.LOAD_TRUNCATED_IMAGES is False,
        )

        # 9) decode_mode()가 중첩/예외 상황에서도 이전 값을 정확히 복원하는지
        with decode_mode(True):
            inner_on = ImageFile.LOAD_TRUNCATED_IMAGES
            with decode_mode(False):
                inner_off = ImageFile.LOAD_TRUNCATED_IMAGES
            restored_after_nesting = ImageFile.LOAD_TRUNCATED_IMAGES
        check("decode_mode(True) 안에서는 플래그가 켜져 있다", inner_on is True)
        check("decode_mode(False)로 중첩하면 꺼진다", inner_off is False)
        check("중첩에서 빠져나오면 바깥 값(True)으로 복원된다", restored_after_nesting is True)
        check("컨텍스트를 다 빠져나오면 원래 값(False)으로 복원된다", ImageFile.LOAD_TRUNCATED_IMAGES is False)

        try:
            with decode_mode(True):
                raise RuntimeError("디코딩 중 예외")
        except RuntimeError:
            pass
        check("예외로 빠져나가도 플래그가 복원된다", ImageFile.LOAD_TRUNCATED_IMAGES is False)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_analyzer()
    print("OK")
