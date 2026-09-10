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

안전장치(2026-09-11, 유료화 준비 검토 중 core/deblur.py와 나란히 추가): 디블러와
같은 아키텍처 계열(NAFNet)이라 같은 종류의 도메인 밖 발산 위험이 있는데, 정작
디노이즈엔 안전장치가 없었다 — RESTORATION_QUALITY_PLAN.md P0 항목.
사전 점검은 core.quality_diagnosis가 쓰는 것과 같은 노이즈 지표(중앙 크롭 +
미디언필터 잔차 stddev, NOISE_RESIDUAL_STDDEV_THRESHOLD)를 그대로 재사용 —
이미 실측 튜닝된 상수라 새로 정할 필요 없음.
사후 점검은 디블러처럼 과거 사고 사례의 실측 비율을 따라간 게 아니다(디노이즈의
실제 발산 사례가 아직 보고된 적이 없어 재현 불가) — 대신 "디노이징은 정의상
출력의 edge variance를 입력보다 늘려선 안 된다"는 원리적 불변식을 쓴다
(experiments/denoise_safety_prototype/measure.py 실측: 정상 케이스 ratio
0.14~0.99, 전부 1 미만). 나중에 실제 발산 사례가 보고되면 그 실측치로
임계값을 다시 맞출 것.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

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


class DenoiseCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


class DenoiseNotRecommendedError(Exception):
    """사전 점검 실패: core.quality_diagnosis 기준으로 "노이즈 추정"이 아닌,
    이미 노이즈가 적은 사진일 때. core/deblur.py의 DeblurNotRecommendedError와
    같은 이유 — SIDD 전용 가중치라 노이즈 없는 입력엔 도메인을 벗어난다."""


class DenoiseResultUnstableError(Exception):
    """사후 점검 실패: 출력의 edge variance가 입력보다 늘어났을 때 — 노이즈를
    "제거"하는 모델이라면 이런 일이 있어서는 안 된다(원리적으로 출력은 입력보다
    같거나 매끈해야 함). 늘어났다면 모델이 도메인 밖 입력에 발산해 오히려
    노이즈/아티팩트를 더한 신호로 보고 저장하지 않는다."""


# experiments/denoise_safety_prototype/measure.py 실측: 정상 케이스(합성 노이즈
# 입력 포함) ratio 0.14~0.99 — 전부 1 미만. 디노이징이 정상 작동하면 출력이
# 입력보다 매끈해지거나 같아야 한다는 원리적 불변식이라, 여유를 크게 둬도
# (1.5배) 정상 케이스를 오탐할 일은 없다.
_RESULT_EDGE_VARIANCE_RATIO_LIMIT = 1.5
# 원본이 극단적으로 밋밋해(분모가 0에 가까워) 비율이 인위적으로 폭주하는 것을
# 방지 — core/deblur.py와 동일한 안전장치, 같은 값.
_RESULT_EDGE_VARIANCE_RATIO_FLOOR = 50.0


def _measure_noise_stddev(bgr_image) -> float:
    """core.quality_diagnosis.assess_quality_issues()와 같은 공식(중앙
    NOISE_CROP_SIZE 크롭 + 3x3 미디언필터 잔차 stddev)으로 노이즈 정도를 잰다.
    파일을 다시 열어 재계산하지 않고 이미 메모리에 있는 BGR 배열로 계산한다 —
    core/deblur.py._measure_edge_variance()와 같은 이유(HEIC 등)."""
    import cv2
    from PIL import Image, ImageChops, ImageFilter, ImageStat

    from core.quality_diagnosis import _center_crop, NOISE_CROP_SIZE

    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    gray = Image.fromarray(rgb).convert("L")
    sample = _center_crop(gray, NOISE_CROP_SIZE)
    denoised = sample.filter(ImageFilter.MedianFilter(size=3))
    residual = ImageChops.difference(sample, denoised)
    return ImageStat.Stat(residual).stddev[0]


def _measure_edge_variance(bgr_image) -> float:
    """core/deblur.py._measure_edge_variance()와 완전히 동일 — 사후 점검용
    edge variance."""
    import cv2
    from PIL import Image

    from core.quality_diagnosis import _edge_variance, QUALITY_ANALYSIS_MAX_SIDE

    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    gray = Image.fromarray(rgb).convert("L")
    gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))
    return _edge_variance(gray)


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

    from core.torch_device import resolve_device

    # options/test/SIDD/NAFNet-width32.yml의 network_g 설정과 정확히 일치해야
    # state_dict가 로드된다(core/deblur.py의 GoPro 설정과 다름).
    net = NAFNet(img_channel=3, width=32, middle_blk_num=12, enc_blk_nums=[2, 2, 4, 8], dec_blk_nums=[2, 2, 2, 2])
    ckpt = torch.load(str(_CKPT_PATH), map_location="cpu")
    net.load_state_dict(ckpt["params"], strict=True)
    net.eval()

    device = resolve_device()
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

    from core.quality_diagnosis import NOISE_RESIDUAL_STDDEV_THRESHOLD

    input_noise_stddev = _measure_noise_stddev(src_img)
    if input_noise_stddev <= NOISE_RESIDUAL_STDDEV_THRESHOLD:
        raise DenoiseNotRecommendedError("이 사진은 노이즈가 적어서 디노이즈 효과가 크지 않을 것 같아요.")

    report(1, 3, "모델 준비 중")
    check_cancel()
    net, device = _get_model()

    check_cancel()
    report(2, 3, "보정 중")

    input_edge_var = _measure_edge_variance(src_img)

    img_rgb = cv2.cvtColor(src_img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = torch.from_numpy(img_rgb.transpose(2, 0, 1)).unsqueeze(0).to(device)

    with torch.no_grad():
        out = net(tensor)

    out_np = out.squeeze(0).clamp(0, 1).cpu().numpy().transpose(1, 2, 0)
    out_bgr = cv2.cvtColor((out_np * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

    output_edge_var = _measure_edge_variance(out_bgr)
    denom = max(input_edge_var, _RESULT_EDGE_VARIANCE_RATIO_FLOOR)
    if output_edge_var / denom > _RESULT_EDGE_VARIANCE_RATIO_LIMIT:
        raise DenoiseResultUnstableError(
            "보정 결과가 비정상적으로 나와서 저장하지 않았어요. 이 사진에는 디노이즈가 맞지 않는 것 같아요."
        )

    check_cancel()
    report(3, 3, "저장 중")

    dest = unique_recovered_path(Path(output_dir), src_path.name, ".png", suffix=suffix)
    ok, buf = cv2.imencode(".png", out_bgr)
    if not ok:
        raise RuntimeError("보정된 이미지를 저장하지 못했습니다.")
    buf.tofile(str(dest))
    return str(dest)
