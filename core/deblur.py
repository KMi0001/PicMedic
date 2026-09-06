"""
core/deblur.py

"디블러" — NAFNet(Megvii, MIT)의 GoPro 데이터셋(고속카메라로 찍은 프레임을
합성한 모션 블러 쌍) 전용 가중치로 손떨림 블러를 보정한다. core/denoise.py
("디노이즈", SIDD 데이터셋 전용 가중치)와 원래 하나의 "디블러/디노이즈"
기능이었다가 분리했다 — NAFNet 공식 저장소 README를 보면 이 둘이 완전히
별도로 학습된 체크포인트라, 디블러 모델로 노이즈를 없애려 하거나 그 반대를
하면 학습 도메인을 벗어나 오히려 결과가 나빠질 수 있다(2026-09-06, 사용자
피드백으로 분리 결정). core/face_restorer.py의 "얼굴 복원"이 얼굴에만 먹히는
것과 달리, 이건 사람이 없는 사진(풍경/사물)에도 범용으로 적용된다.
core/converter.py와 같은 원칙: 원본은 절대 건드리지 않고 항상 새 파일을 만든다.

experiments/restore_prototype/에서 검증: 합성 old/blurry 테스트 이미지에
돌려서, 언샤프 마스크 같은 링잉 부작용 없이 경계가 또렷해지는 걸 확인했다.
얼굴 디테일을 새로 그려 넣는 얼굴 복원과 달리 "있는 정보를 더 선명하게" 하는
쪽이라 화질 개선(Real-ESRGAN)에 더 가깝지만, 확대가 아니라 원본 해상도 그대로
보정한다는 점이 다르다.

torch/vendor 모듈은 이 파일 최상단이 아니라 함수 안에서 지연 import한다 —
core/face_restorer.py와 같은 이유(앱 시작 속도).

필요 자산: assets/deblur/ 아래 NAFNet-GoPro-width32.pth(scripts/
fetch_deblur_assets.py로 받는다, 구글드라이브 호스팅이라 gdown 필요). 없으면
is_available()이 False라 GUI 쪽에서 버튼을 감춘다.

gui/batch_ai_screen.py에서 여러 장을 고르면 deblur_batch()가 한 장씩 순서대로
처리한다(core/quality_enhancer.py::enhance_batch와 같은 패턴).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from models.file_info import FileInfo
from utils.file_utils import unique_recovered_path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets" / "deblur"
_CKPT_PATH = _ASSETS_DIR / "NAFNet-GoPro-width32.pth"
_VENDOR_DIR = _PROJECT_ROOT / "vendor" / "basicsr_min"

_HEIC_EXTENSIONS = (".heic", ".heif")

# experiments/restore_prototype 실측(720x900=0.65MP → 3.3초, CPU) 기반 대략치.
_ESTIMATE_FIXED_SECONDS = 0.5
_ESTIMATE_SECONDS_PER_MEGAPIXEL = 5.0

_model_cache = None  # NAFNet 인스턴스 캐시 — 세션 중 반복 사용 시 재로딩 방지


def is_available() -> bool:
    """이 기기에서 디블러/디노이즈 기능을 쓸 수 있는지(가중치 파일이 준비됐는지)."""
    return _CKPT_PATH.exists()


def estimate_seconds(width: int, height: int) -> float:
    """대략적인 예상 소요 시간(초, CPU 기준) — 확인 팝업 안내용."""
    megapixels = (width * height) / 1_000_000
    return _ESTIMATE_FIXED_SECONDS + _ESTIMATE_SECONDS_PER_MEGAPIXEL * megapixels


def estimate_batch_seconds(files: list[FileInfo]) -> float:
    """여러 장을 순서대로 처리할 때의 총 예상 소요 시간(초) — 해상도를 아는
    파일만 더한다."""
    return sum(estimate_seconds(f.width, f.height) for f in files if f.width and f.height)


class DeblurCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


def _get_model():
    """NAFNet 인스턴스를 지연 생성하고 캐싱한다(모듈 전역, 프로세스 수명 동안
    재사용 — 68MB 체크포인트 로딩을 매번 반복하지 않는다)."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    vendor_str = str(_VENDOR_DIR)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)

    import torch
    from basicsr.models.archs.NAFNet_arch import NAFNet

    net = NAFNet(img_channel=3, width=32, middle_blk_num=1, enc_blk_nums=[1, 1, 1, 28], dec_blk_nums=[1, 1, 1, 1])
    ckpt = torch.load(str(_CKPT_PATH), map_location="cpu")
    net.load_state_dict(ckpt["params"], strict=True)
    net.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net = net.to(device)
    _model_cache = (net, device)
    return _model_cache


def deblur_image(
    input_path: str,
    output_dir: str,
    *,
    suffix: str = "deblurred",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """input_path 사진을 디블러/디노이즈해서 output_dir 안에 새 파일로 저장하고
    그 경로를 반환한다. 원본은 전혀 건드리지 않는다. progress_callback은
    (현재 단계, 전체 단계, 단계 설명)을 받는다 — NAFNet은 한 번의 순전파라
    RestoreFormer++처럼 3단계로만 안내한다. should_cancel()이 True를 반환하면
    DeblurCancelled를 던진다."""
    if not is_available():
        raise RuntimeError("디블러/디노이즈에 필요한 파일을 찾을 수 없습니다.")

    def report(step: int, total: int, label: str):
        if progress_callback:
            progress_callback(step, total, label)

    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise DeblurCancelled()

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
class DeblurOutcome:
    """core/converter.py::RecoveryOutcome과 같은 모양(같은 필드명)으로 맞춰서
    gui/recovery_result_screen.py를 그대로 재사용할 수 있게 한다."""

    original: FileInfo
    output_path: Optional[str] = None
    success: bool = False
    verified: bool = True  # 이 기능엔 별도 검증 단계가 없어 성공하면 그대로 참
    error_message: Optional[str] = None
    skipped: bool = False


def deblur_batch(
    files: list[FileInfo],
    output_dir: str | Path,
    *,
    suffix: str = "deblurred",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[DeblurOutcome]:
    """여러 장을 한 장씩 순서대로 디블러/디노이즈한다(동시 처리 아님 —
    core/converter.py::recover_batch와 같은 순차 반복 + 파일 단위 진행률/취소
    패턴). 파일 하나가 실패해도 나머지는 계속 진행한다."""
    output_dir = Path(output_dir)
    outcomes: list[DeblurOutcome] = []
    total = len(files)
    for idx, info in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        try:
            output_path = deblur_image(info.path, str(output_dir), suffix=suffix, should_cancel=should_cancel)
            outcome = DeblurOutcome(original=info, output_path=output_path, success=True)
        except DeblurCancelled:
            break
        except Exception as exc:  # noqa: BLE001 - 개별 파일 실패가 전체 배치를 막지 않도록
            outcome = DeblurOutcome(original=info, error_message=str(exc))
        outcomes.append(outcome)
        if progress_callback:
            progress_callback(idx, total, info.filename)
    return outcomes
