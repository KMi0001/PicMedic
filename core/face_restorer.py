"""
core/face_restorer.py

"얼굴 복원" — RestoreFormer++로 사진 속 얼굴의 디테일(눈/주름/치아 등)을 실제로
복원한다. core/quality_enhancer.py의 "화질 개선"과 달리 이건 진짜로 사라진
디테일을 그럴듯하게 새로 그려 넣는 AI 복원이다 — 인물이 없는 사진에는 효과가
없고, 얼굴이 아닌 배경은 원본 그대로 남는다. core/converter.py와 같은 원칙:
원본은 절대 건드리지 않고 항상 새 파일을 만든다.

experiments/restore_prototype/에서 검증된 선택 — GFPGAN(라이선스 회색지대:
StyleGAN2/DFDNet 비상업 의존)과 CodeFormer(NTU S-Lab, 비상업 전용)는 배제하고
RestoreFormer++(Apache 2.0, 상업 이용에 문제 없음)를 채택했다.

torch/facexlib/vendor 모듈은 이 파일 최상단이 아니라 함수 안에서 지연 import
한다 — 앱 시작 시 무거운 PyTorch를 매번 로딩하면 이 기능을 안 쓰는 사용자도
느려지므로, 실제로 "얼굴 복원"을 실행할 때만 비용을 낸다.

필요 자산: assets/face_restore/ 아래 RestoreFormer++.ckpt + facexlib 가중치
2개(scripts/fetch_face_restore_assets.py로 받는다). 없으면 is_available()이
False라 GUI 쪽에서 버튼을 감춘다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from utils.file_utils import unique_recovered_path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets" / "face_restore"
_CKPT_PATH = _ASSETS_DIR / "RestoreFormer++.ckpt"
_FACEXLIB_WEIGHTS_DIR = _ASSETS_DIR / "facexlib"
_VENDOR_DIRS = [_PROJECT_ROOT / "vendor" / "basicsr_min", _PROJECT_ROOT / "vendor" / "restoreformer"]

_HEIC_EXTENSIONS = (".heic", ".heif")

# experiments/restore_prototype에서 실측: 모델 로딩 ~1초(캐시 후 재사용 시
# 0초) + 얼굴 1개당 약 5초(CPU 기준, 10045.png 3인 가족사진 = 16초). GPU가
# 없는 대부분의 사용자 기기 기준이라 이미 보수적인 값 — 안내 팝업용 대략치.
_ESTIMATE_FIXED_SECONDS = 3.0
_ESTIMATE_SECONDS_PER_FACE = 5.0
# 얼굴 개수는 실행 전엔 알 수 없으므로, 안내 팝업에서는 "사진 1장에 흔히 있는
# 얼굴 수(1~3명)" 기준 범위로 보여준다.
_ESTIMATE_TYPICAL_MIN_FACES = 1
_ESTIMATE_TYPICAL_MAX_FACES = 3

_restorer_cache = None  # RestoreFormer 인스턴스 캐시 — 세션 중 반복 사용 시 280MB 체크포인트 재로딩 방지


def is_available() -> bool:
    """이 기기에서 얼굴 복원 기능을 쓸 수 있는지(가중치 파일이 준비됐는지)."""
    return (
        _CKPT_PATH.exists()
        and (_FACEXLIB_WEIGHTS_DIR / "detection_Resnet50_Final.pth").exists()
        and (_FACEXLIB_WEIGHTS_DIR / "parsing_parsenet.pth").exists()
    )


def estimate_seconds_range() -> tuple[float, float]:
    """대략적인 예상 소요 시간 범위(초) — 확인 팝업 안내용. 얼굴 수는 실행
    전엔 알 수 없어서 "흔한 경우"의 범위로 보여준다."""
    low = _ESTIMATE_FIXED_SECONDS + _ESTIMATE_SECONDS_PER_FACE * _ESTIMATE_TYPICAL_MIN_FACES
    high = _ESTIMATE_FIXED_SECONDS + _ESTIMATE_SECONDS_PER_FACE * _ESTIMATE_TYPICAL_MAX_FACES
    return low, high


class FaceRestorationCancelled(Exception):
    """사용자가 처리 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


class NoFaceFoundError(Exception):
    """사진에서 얼굴을 하나도 찾지 못했을 때 — 오류가 아니라 "이 사진엔 효과가
    없다"는 안내로 GUI에서 다르게 처리하기 위해 구분한다."""


def _get_restorer():
    """RestoreFormer 인스턴스를 지연 생성하고 캐싱한다(모듈 전역, 프로세스
    수명 동안 재사용 — 체크포인트 로딩이 몇 초 걸리므로 매번 새로 만들지
    않는다)."""
    global _restorer_cache
    if _restorer_cache is not None:
        return _restorer_cache

    for vendor_dir in _VENDOR_DIRS:
        vendor_str = str(vendor_dir)
        if vendor_str not in sys.path:
            sys.path.insert(0, vendor_str)

    import torch
    from RestoreFormer.RestoreFormer import RestoreFormer

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _restorer_cache = RestoreFormer(
        model_path=str(_CKPT_PATH),
        upscale=1,
        arch="RestoreFormer++",
        bg_upsampler=None,
        device=device,
        face_model_rootpath=str(_FACEXLIB_WEIGHTS_DIR),
    )
    return _restorer_cache


def restore_face(
    input_path: str,
    output_dir: str,
    *,
    suffix: str = "restored",
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """input_path 사진의 얼굴을 복원해서 output_dir 안에 새 파일로 저장하고 그
    경로를 반환한다. 원본은 전혀 건드리지 않는다. progress_callback은
    (현재 단계, 전체 단계, 단계 설명)을 받는다 — Real-ESRGAN의 %와 달리
    RestoreFormer++는 세밀한 진행률을 안 주므로 3단계로만 안내한다.
    should_cancel()이 True를 반환하면 EnhancementCancelled를 던진다.
    얼굴을 하나도 못 찾으면 NoFaceFoundError를 던진다."""
    if not is_available():
        raise RuntimeError("얼굴 복원에 필요한 파일을 찾을 수 없습니다.")

    def report(step: int, total: int, label: str):
        if progress_callback:
            progress_callback(step, total, label)

    def check_cancel():
        if should_cancel is not None and should_cancel():
            raise FaceRestorationCancelled()

    src_path = Path(input_path)

    report(1, 3, "모델 준비 중")
    check_cancel()
    restorer = _get_restorer()

    check_cancel()
    report(2, 3, "얼굴 인식 및 복원 중")

    import cv2
    import numpy as np

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

    cropped_faces, _, restored_img = restorer.enhance(
        src_img, has_aligned=False, only_center_face=False, paste_back=True
    )
    if not cropped_faces:
        raise NoFaceFoundError("사진에서 얼굴을 찾지 못했습니다.")

    check_cancel()
    report(3, 3, "저장 중")

    dest = unique_recovered_path(Path(output_dir), src_path.name, ".png", suffix=suffix)
    ok, buf = cv2.imencode(".png", restored_img)
    if not ok:
        raise RuntimeError("복원된 이미지를 저장하지 못했습니다.")
    buf.tofile(str(dest))
    return str(dest)
