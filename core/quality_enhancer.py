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
  오래 걸리고 얻는 이득은 오히려 적다 — gui/detail_screen.py/gui/home_screen.py의
  단일 파일 진입점은 여전히 한 장씩만 다루고, gui/batch_ai_screen.py에서 여러
  장을 고르면 아래 enhance_batch()가 순서대로(동시에가 아니라) 처리하면서 매
  장마다 진행률/취소를 보여준다 — "빨라진 게 아니라 여러 장을 순서대로 기다리는
  것"임을 UI에서 예상 소요 시간으로 미리 안내한다(사용자 요청, 2026-09-06).

필요 자산: assets/realesrgan/ 아래 실행 파일 + 모델(현재 Windows만 준비돼
있음 — scripts/fetch_realesrgan_assets.py로 받는다). 없으면 is_available()이
False라 GUI 쪽에서 버튼을 감춘다(macOS는 아직 별도 바이너리 필요, 미해결).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from models.file_info import FileInfo
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


@dataclass
class EnhanceOutcome:
    """core/converter.py::RecoveryOutcome과 같은 모양(같은 필드명)으로 맞춰서
    gui/recovery_result_screen.py를 그대로 재사용할 수 있게 한다."""

    original: FileInfo
    output_path: Optional[str] = None
    success: bool = False
    verified: bool = True  # 이 기능엔 별도 검증 단계가 없어 성공하면 그대로 참
    error_message: Optional[str] = None
    skipped: bool = False


def estimate_batch_seconds(files: list[FileInfo]) -> float:
    """여러 장을 순서대로 처리할 때의 총 예상 소요 시간(초) — 해상도를 아는
    파일만 더한다(모르는 파일은 대략치를 못 구하니 안내에서 "이상"으로 표시)."""
    return sum(
        estimate_seconds(f.width, f.height) for f in files if f.width and f.height
    )


def enhance_batch(
    files: list[FileInfo],
    output_dir: str | Path,
    *,
    suffix: str = "upscaled",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[EnhanceOutcome]:
    """여러 장을 한 장씩 순서대로 화질 개선한다(동시 처리 아님 — core/converter.py::
    recover_batch와 같은 순차 반복 + 파일 단위 진행률/취소 패턴). 파일 하나가
    실패해도 나머지는 계속 진행한다."""
    output_dir = Path(output_dir)
    outcomes: list[EnhanceOutcome] = []
    total = len(files)
    for idx, info in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        try:
            output_path = enhance_quality(info.path, str(output_dir), suffix=suffix, should_cancel=should_cancel)
            outcome = EnhanceOutcome(original=info, output_path=output_path, success=True)
        except EnhancementCancelled:
            break
        except Exception as exc:  # noqa: BLE001 - 개별 파일 실패가 전체 배치를 막지 않도록
            outcome = EnhanceOutcome(original=info, error_message=str(exc))
        outcomes.append(outcome)
        if progress_callback:
            progress_callback(idx, total, info.filename)
    return outcomes
