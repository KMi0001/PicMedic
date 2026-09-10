"""
core/quality_enhancer.py

Phase 2 "화질 개선"(실험적) — Real-ESRGAN(ncnn-vulkan)으로 사진 한 장을
업스케일한다. core/converter.py와 같은 원칙: 원본은 절대 건드리지 않고 항상
새 파일을 만든다.

정확히 뭘 하는 기능인지(과장하지 않기 위한 메모):
- 사라진 디테일을 "복원"하는 게 아니라, 단순 확대(bicubic)보다 덜 뭉개지게
  "그럴듯하게" 확대하는 것 — experiments/upscale_prototype에서 실측 비교로
  확인됨(PicMedic-Web의 화질 판정과는 무관).
- 처리 시간이 출력 픽셀 수(원본 × scale²)에 비례해서, 이미 고화질인 사진일수록
  오래 걸리고 얻는 이득은 오히려 적다 — 폴더 일괄 처리가 아니라
  gui/detail_screen.py/gui/home_screen.py에서 사진 한 장 단위로만 제공한다.

필요 자산: assets/realesrgan/ 아래 실행 파일 + 모델(현재 Windows만 준비돼
있음 — scripts/fetch_realesrgan_assets.py로 받는다). 없으면 is_available()이
False라 GUI 쪽에서 버튼을 감춘다(macOS는 아직 별도 바이너리 필요, 미해결).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from utils import trash
from utils.file_utils import unique_recovered_path

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "realesrgan"
_EXE_PATH = _ASSETS_DIR / "realesrgan-ncnn-vulkan.exe"
MODEL_NAME = "realesrgan-x4plus"
SCALE = 4

_HEIC_EXTENSIONS = (".heic", ".heif")

# experiments/upscale_prototype 실측 벤치마크(800x600=5.3s, 1600x1200=12.0s,
# 4032x3024=66.3s, GPU 기준) 기반 대략적인 소요 시간 추정 — 정확한 수치가
# 아니라 확인 팝업에서 "이 정도 걸릴 수 있다"는 감을 미리 보여주기 위함.
# GPU가 없는 기기에서는 훨씬 더 걸릴 수 있음을 문구로 같이 안내한다.
_ESTIMATE_FIXED_SECONDS = 2.8
_ESTIMATE_SECONDS_PER_MEGAPIXEL = 5.2


def is_available() -> bool:
    """이 기기/플랫폼에서 화질 개선 기능을 쓸 수 있는지(실행 파일이 준비됐는지)."""
    return _EXE_PATH.exists()


def estimate_seconds(width: int, height: int) -> float:
    """대략적인 예상 소요 시간(초, GPU 기준) — 확인 팝업 안내용."""
    megapixels = (width * height) / 1_000_000
    return _ESTIMATE_FIXED_SECONDS + _ESTIMATE_SECONDS_PER_MEGAPIXEL * megapixels


class EnhancementCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


def enhance_quality(
    input_path: str,
    output_dir: str,
    *,
    suffix: str = "upscaled",
    progress_callback: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """input_path의 사진을 업스케일해서 output_dir 안에 새 파일로 저장하고 그
    경로를 반환한다. 원본은 전혀 건드리지 않는다. progress_callback은 0~100
    사이 값을 받는다(realesrgan-ncnn-vulkan.exe가 stderr에 찍는 진행률).
    should_cancel()이 True를 반환하면 실행 중인 프로세스를 종료하고
    EnhancementCancelled를 던진다."""
    if not is_available():
        raise RuntimeError("화질 개선 실행 파일을 찾을 수 없습니다.")

    src_path = Path(input_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # realesrgan.exe도 OpenCV처럼 Windows에서 비ASCII(한글 등) 경로 입출력이
        # 불안정할 수 있어서, 항상 ASCII 임시 경로로 옮겨서 처리한다. HEIC는
        # exe가 아예 못 읽으므로 PNG로 먼저 디코딩한다.
        if src_path.suffix.lower() in _HEIC_EXTENSIONS:
            import pillow_heif

            pillow_heif.register_heif_opener()
            tmp_in = tmp_dir / "input.png"
            with Image.open(src_path) as img:
                img.convert("RGB").save(tmp_in)
        else:
            tmp_in = tmp_dir / f"input{src_path.suffix.lower()}"
            tmp_in.write_bytes(src_path.read_bytes())

        tmp_out = tmp_dir / "output.png"

        proc = subprocess.Popen(
            [
                str(_EXE_PATH),
                "-i", str(tmp_in),
                "-o", str(tmp_out),
                "-n", MODEL_NAME,
                "-s", str(SCALE),
            ],
            cwd=str(_EXE_PATH.parent),  # models/ 폴더를 상대경로로 찾으므로 exe 폴더에서 실행
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        stderr_lines: list[str] = []
        cancelled = False
        if proc.stderr is not None:
            for line in proc.stderr:
                if should_cancel is not None and should_cancel():
                    proc.terminate()
                    cancelled = True
                    break
                line = line.strip()
                stderr_lines.append(line)
                if progress_callback and line.endswith("%"):
                    try:
                        progress_callback(float(line[:-1]))
                    except ValueError:
                        pass
        proc.wait(timeout=600)

        if cancelled:
            raise EnhancementCancelled()

        if proc.returncode != 0 or not tmp_out.exists():
            detail = stderr_lines[-1] if stderr_lines else f"exit code {proc.returncode}"
            raise RuntimeError(f"화질 개선 실행에 실패했습니다: {detail}")

        dest = unique_recovered_path(Path(output_dir), src_path.name, ".png", suffix=suffix)
        dest.write_bytes(tmp_out.read_bytes())
        return str(dest)


def enhance_quality_replacing_original(
    input_path: str,
    *,
    progress_callback: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[str, str]:
    """"원본 삭제" 옵션(사용자가 명시적으로 켠 경우에만, 2026-09-10 요청)을 위한
    경로 — core/converter.py::_recover_file_replacing_original과 같은 방식.
    원본을 그 파일이 있던 폴더의 임시휴지통으로 먼저 옮겨 자리를 비운 뒤, 그
    자리에(원본 이름 + .png) 업스케일 결과를 저장해서 "대체"한다. 실패하거나
    취소되면(EnhancementCancelled 포함) 옮겨둔 원본을 즉시 되돌리고 그대로
    다시 던진다. 반환값은 (결과 경로, 원본이 옮겨간 임시휴지통 경로) — 호출부가
    "원본(이동 전) 미리보기"를 계속 보여주거나, 나중에 되돌려야 할 때 씀."""
    original_path = Path(input_path)
    output_dir = original_path.parent
    trashed_path = trash.move_to_trash(original_path, reason="화질 개선 — 원본 대체")

    try:
        result_path = enhance_quality(
            str(trashed_path), str(output_dir), progress_callback=progress_callback, should_cancel=should_cancel
        )
    except Exception:
        try:
            trash.restore_from_trash(trashed_path)
        except (ValueError, OSError):
            pass  # 되돌리기 실패해도 원본 자체는 임시휴지통에 안전하게 남아있다
        raise

    # unique_recovered_path는 항상 "_upscaled" 같은 문구를 붙인다 — 원본은 이미
    # 치웠으니 필요 없어서, 결과를 "원본 이름 + .png"로 다시 이름 붙인다
    # (core/converter.py::_recover_file_replacing_original과 같은 이유).
    produced = Path(result_path)
    desired = output_dir / f"{original_path.stem}{produced.suffix}"
    if desired != produced and not desired.exists():
        produced.rename(desired)
        result_path = str(desired)
    return result_path, str(trashed_path)
