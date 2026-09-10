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

안전장치(2026-09-08, 사용자가 컬러 노이즈로 망가진 결과를 실제로 겪은 뒤 추가):
NAFNet-GoPro는 합성 모션 블러 전용이라 도메인 밖 입력(이미 선명한 사진)엔 발산해서
결과가 통째로 망가질 수 있다. 사전 점검(DeblurNotRecommendedError)이 걸러낸다 —
처음엔 전역 edge variance만 봐서 하늘/바다처럼 큰 면적이 매끈해 실제로는 안
흐린데도 이 점검을 통과해버리는 사진이 있었는데, core/quality_diagnosis.py의
블러 휴리스틱을 4x4 타일 90퍼센타일 방식으로 바꾸면서 사전 점검도 같은 지표를
쓰도록 맞춰 대부분 걸러진다(같은 날). 그래도 모델 자체가 예상 밖으로 발산하는
경우에 대비해 사후 점검(출력 edge variance 폭증 감지, DeblurResultUnstableError)을
마지막 방어선으로 남겨둔다 — 이쪽은 전역 edge variance 그대로 쓴다(비율 임계값이
그 지표로 실측 보정돼 있음). 임계값은 experiments/deblur_safety_prototype/measure.py
실측 기반.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

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


class DeblurCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


class DeblurNotRecommendedError(Exception):
    """사전 점검 실패: core.quality_diagnosis 기준으로 "블러 추정"이 아닌,
    이미 선명한 사진일 때. NAFNet-GoPro는 합성 모션 블러 전용으로 학습돼서
    블러 없는 입력엔 도메인을 벗어나 오히려 결과를 컬러 노이즈로 망가뜨릴 수
    있다(2026-09-08, 사용자가 실제로 겪은 사례 보고)."""


class DeblurResultUnstableError(Exception):
    """사후 점검 실패: 출력의 edge variance가 원본 대비 비정상적으로
    폭증했을 때 — 모델이 도메인 밖 입력에 발산해 컬러 노이즈로 망가진
    신호라 저장하지 않고 실패로 처리한다. 사전 점검(위)만으로는 못 거른다 —
    실측해보니 하늘/바다처럼 큰 면적이 매끈한, 실제로는 안 흐린 사진도
    edge variance가 낮게 나와 "블러 추정"에 걸려버려서 모델까지 들어간다
    (experiments/deblur_safety_prototype/measure.py). 임계값은 같은 스크립트
    실측 기반: 정상 결과는 원본 대비 ratio ~1.0, 망가진 결과는 ratio ~44였다."""


# experiments/deblur_safety_prototype/measure.py 실측: 정상 1.03배 vs 망가짐 43.82배.
# 강한 정상 보정에도 여유를 두면서 망가짐과는 확실히 구분되게 중간값보다 낮게 잡음.
_RESULT_EDGE_VARIANCE_RATIO_LIMIT = 10.0
# 원본이 극단적으로 밋밋해(분모가 0에 가까워) 비율이 인위적으로 폭주하는 것을 방지.
_RESULT_EDGE_VARIANCE_RATIO_FLOOR = 50.0


def _measure_edge_variance(bgr_image) -> float:
    """core.quality_diagnosis와 같은 공식(그레이스케일 512px 축소 + FIND_EDGES
    분산)으로 전역 edge variance를 잰다. 파일을 다시 열어 재계산하지 않고 이미
    메모리에 있는 BGR 배열로 계산한다 — HEIC처럼 PIL이 바로 못 여는 포맷도
    이 함수를 거치면 문제없다(deblur_image()가 이미 디코딩해뒀으므로).

    사후 안정성 비율 검사(DeblurResultUnstableError) 전용 — 그 임계값(비율
    10.0/바닥값 50.0)이 이 전역 지표로 실측 보정돼 있어(2026-09-08) 그대로
    둔다. 사전 추천 여부 판단은 아래 _measure_tile_percentile_edge_variance."""
    import cv2
    from PIL import Image

    from core.quality_diagnosis import _edge_variance, QUALITY_ANALYSIS_MAX_SIDE

    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    gray = Image.fromarray(rgb).convert("L")
    gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))
    return _edge_variance(gray)


def _measure_tile_percentile_edge_variance(bgr_image) -> float:
    """사전 점검(DeblurNotRecommendedError)용 edge variance. core.quality_diagnosis
    .assess_quality_issues()가 "블러 추정"을 판단할 때 쓰는 것과 완전히 같은
    지표(4x4 타일 90퍼센타일)를 써야 같은 기준으로 판단한다 — 원래는 여기도
    전역 edge variance를 썼는데, 하늘/바다처럼 매끈한 배경이 큰 사진에서
    quality_diagnosis는 이미 "블러 아님"으로 고쳐졌는데 이 사전 점검만 옛
    지표를 써서 여전히 모델까지 들여보내는 불일치가 생겨 맞췄다(2026-09-08,
    core/quality_diagnosis.py의 블러 휴리스틱 교체와 함께)."""
    import cv2
    from PIL import Image

    from core.quality_diagnosis import _tile_percentile_edge_variance, QUALITY_ANALYSIS_MAX_SIDE

    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    gray = Image.fromarray(rgb).convert("L")
    gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))
    return _tile_percentile_edge_variance(gray)


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

    from core.torch_device import resolve_device

    net = NAFNet(img_channel=3, width=32, middle_blk_num=1, enc_blk_nums=[1, 1, 1, 28], dec_blk_nums=[1, 1, 1, 1])
    ckpt = torch.load(str(_CKPT_PATH), map_location="cpu")
    net.load_state_dict(ckpt["params"], strict=True)
    net.eval()

    device = resolve_device()
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

    from core.quality_diagnosis import BLUR_EDGE_VARIANCE_THRESHOLD

    if _measure_tile_percentile_edge_variance(src_img) >= BLUR_EDGE_VARIANCE_THRESHOLD:
        raise DeblurNotRecommendedError("이 사진은 이미 선명해서 디블러 효과가 크지 않을 것 같아요.")

    input_edge_var = _measure_edge_variance(src_img)

    report(1, 3, "모델 준비 중")
    check_cancel()
    net, device = _get_model()

    check_cancel()
    report(2, 3, "보정 중")

    img_rgb = cv2.cvtColor(src_img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    tensor = torch.from_numpy(img_rgb.transpose(2, 0, 1)).unsqueeze(0).to(device)

    with torch.no_grad():
        out = net(tensor)

    out_np = out.squeeze(0).clamp(0, 1).cpu().numpy().transpose(1, 2, 0)
    out_bgr = cv2.cvtColor((out_np * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

    output_edge_var = _measure_edge_variance(out_bgr)
    denom = max(input_edge_var, _RESULT_EDGE_VARIANCE_RATIO_FLOOR)
    if output_edge_var / denom > _RESULT_EDGE_VARIANCE_RATIO_LIMIT:
        raise DeblurResultUnstableError(
            "보정 결과가 비정상적으로 나와서 저장하지 않았어요. 이 사진에는 디블러가 맞지 않는 것 같아요."
        )

    check_cancel()
    report(3, 3, "저장 중")

    dest = unique_recovered_path(Path(output_dir), src_path.name, ".png", suffix=suffix)
    ok, buf = cv2.imencode(".png", out_bgr)
    if not ok:
        raise RuntimeError("보정된 이미지를 저장하지 못했습니다.")
    buf.tofile(str(dest))
    return str(dest)
