"""
core/denoise.py

"디노이즈" — NAFNet(Megvii, MIT)의 SIDD 데이터셋(스마트폰 센서의 실제 저조도
노이즈) 전용 가중치로 노이즈를 제거한다. core/deblur.py("디블러", GoPro
데이터셋 전용 가중치)와 원래 하나의 "디블러/디노이즈" 기능이었다가 분리했다 —
NAFNet 공식 저장소 README를 보면 이 둘이 완전히 별도로 학습된 체크포인트고,
아키텍처 블록 구성(enc/middle/dec block 수)도 서로 다르다(SIDD가 GoPro보다
훨씬 깊다: middle_blk_num 12 vs 1). 디블러 모델로 노이즈를 없애려 하면 학습
도메인을 벗어나 오히려 결과가 나빠질 수 있다(2026-09-06, 사용자 피드백으로
분리 결정). 그 외 구조(지연 import, is_available, 배치 지원)는
core/deblur.py와 동일한 원칙.

필요 자산: assets/denoise/ 아래 NAFNet-SIDD-width32.pth(scripts/
fetch_denoise_assets.py로 받는다, 구글드라이브 호스팅이라 gdown 필요). 없으면
is_available()이 False라 GUI 쪽에서 버튼을 감춘다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from models.file_info import FileInfo
from utils.file_utils import unique_recovered_path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets" / "denoise"
_CKPT_PATH = _ASSETS_DIR / "NAFNet-SIDD-width32.pth"
_VENDOR_DIR = _PROJECT_ROOT / "vendor" / "basicsr_min"

_HEIC_EXTENSIONS = (".heic", ".heif")

# 실측(10045.png, 3.6MP, CPU): 9.3초 → 약 2.3초/MP + 고정 1초.
_ESTIMATE_FIXED_SECONDS = 1.0
_ESTIMATE_SECONDS_PER_MEGAPIXEL = 2.5

_model_cache = None  # NAFNet 인스턴스 캐시 — 세션 중 반복 사용 시 재로딩 방지


def is_available() -> bool:
    """이 기기에서 디노이즈 기능을 쓸 수 있는지(가중치 파일이 준비됐는지)."""
    return _CKPT_PATH.exists()


def estimate_seconds(width: int, height: int) -> float:
    """대략적인 예상 소요 시간(초, CPU 기준) — 확인 팝업 안내용."""
    megapixels = (width * height) / 1_000_000
    return _ESTIMATE_FIXED_SECONDS + _ESTIMATE_SECONDS_PER_MEGAPIXEL * megapixels


def estimate_batch_seconds(files: list[FileInfo]) -> float:
    """여러 장을 순서대로 처리할 때의 총 예상 소요 시간(초) — 해상도를 아는
    파일만 더한다."""
    return sum(estimate_seconds(f.width, f.height) for f in files if f.width and f.height)


class DenoiseCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


def _get_model():
    """NAFNet(SIDD 구성) 인스턴스를 지연 생성하고 캐싱한다(모듈 전역, 프로세스
    수명 동안 재사용 — 117MB 체크포인트 로딩을 매번 반복하지 않는다)."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    vendor_str = str(_VENDOR_DIR)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)

    import torch
    from basicsr.models.archs.NAFNet_arch import NAFNet

    # options/test/SIDD/NAFNet-width32.yml의 network_g 설정과 정확히 일치해야
    # state_dict가 로드된다(core/deblur.py의 GoPro 설정과 다름).
    net = NAFNet(img_channel=3, width=32, middle_blk_num=12, enc_blk_nums=[2, 2, 4, 8], dec_blk_nums=[2, 2, 2, 2])
    ckpt = torch.load(str(_CKPT_PATH), map_location="cpu")
    net.load_state_dict(ckpt["params"], strict=True)
    net.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = net.to(device)
    _model_cache = (net, device)
    return _model_cache


def denoise_image(
    input_path: str,
    output_dir: str,
    *,
    suffix: str = "denoised",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """input_path 사진을 디노이즈해서 output_dir 안에 새 파일로 저장하고 그
    경로를 반환한다. 원본은 전혀 건드리지 않는다. progress_callback은
    (현재 단계, 전체 단계, 단계 설명)을 받는다. should_cancel()이 True를
    반환하면 DenoiseCancelled를 던진다."""
    if not is_available():
        raise RuntimeError("디노이즈에 필요한 파일을 찾을 수 없습니다.")

    def report(step: int, total: int, label: str):
        if progress_callback:
            progress_callback(step, total, label)

    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise DenoiseCancelled()

    src_path = Path(input_path)

    report(1, 3, "모델 준비 중")
    check_cancel()
    net, device = _get_model()

    check_cancel()
    report(2, 3, "보정 중")

    import cv2
    import numpy as np
    import torch

    if src_path.suffix.lower() in _HEIC_EXTENSIONS:
        from PIL import Image
        import pillow_heif

        pillow_heif.register_heif_opener()
        with Image.open(src_path) as img:
            rgb = np.array(img.convert("RGB"))
        src_img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    else:
        data = np.fromfile(str(src_path), dtype=np.uint8)
        src_img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if src_img is None:
        raise ValueError("이미지를 읽을 수 없습니다(지원하지 않는 형식이거나 손상된 파일).")

    img_rgb = cv2.cvtColor(src_img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = torch.from_numpy(img_rgb.transpose(2, 0, 1)).unsqueeze(0).to(device)

    with torch.no_grad():
        out = net(tensor)

    out_np = out.squeeze(0).clamp(0, 1).cpu().numpy().transpose(1, 2, 0)
    out_bgr = cv2.cvtColor((out_np * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

    check_cancel()
    report(3, 3, "저장 중")

    dest = unique_recovered_path(Path(output_dir), src_path.name, ".png", suffix=suffix)
    ok, buf = cv2.imencode(".png", out_bgr)
    if not ok:
        raise RuntimeError("보정된 이미지를 저장하지 못했습니다.")
    buf.tofile(str(dest))
    return str(dest)


@dataclass
class DenoiseOutcome:
    """core/converter.py::RecoveryOutcome과 같은 모양(같은 필드명)으로 맞춰서
    gui/recovery_result_screen.py를 그대로 재사용할 수 있게 한다."""

    original: FileInfo
    output_path: Optional[str] = None
    success: bool = False
    verified: bool = True  # 이 기능엔 별도 검증 단계가 없어 성공하면 그대로 참
    error_message: Optional[str] = None
    skipped: bool = False


def denoise_batch(
    files: list[FileInfo],
    output_dir: str | Path,
    *,
    suffix: str = "denoised",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[DenoiseOutcome]:
    """여러 장을 한 장씩 순서대로 디노이즈한다(동시 처리 아님 —
    core/converter.py::recover_batch와 같은 순차 반복 + 파일 단위 진행률/취소
    패턴). 파일 하나가 실패해도 나머지는 계속 진행한다."""
    output_dir = Path(output_dir)
    outcomes: list[DenoiseOutcome] = []
    total = len(files)
    for idx, info in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        try:
            output_path = denoise_image(info.path, str(output_dir), suffix=suffix, should_cancel=should_cancel)
            outcome = DenoiseOutcome(original=info, output_path=output_path, success=True)
        except DenoiseCancelled:
            break
        except Exception as exc:  # noqa: BLE001 - 개별 파일 실패가 전체 배치를 막지 않도록
            outcome = DenoiseOutcome(original=info, error_message=str(exc))
        outcomes.append(outcome)
        if progress_callback:
            progress_callback(idx, total, info.filename)
    return outcomes
