"""
core/quality_diagnosis.py

"사진 진단" — 화질 개선/얼굴 복원/디블러/디노이즈 중 어느 걸 눌러야 할지
사용자가 감으로 고르지 않아도 되게, 사진을 실제로 판단해서 추천한다.
core/converter.py 같은 파일 진단이 아니라 "픽셀 내용"을 본다는 점이 다르다.

블러/노출/대비/노이즈 추정(assess_quality_issues)은 PicMedic-Web/core/diagnosis.py
의 같은 함수를 그대로 포팅했다 — Pillow 통계 기반 휴리스틱(ML 아님)이고, 그
저장소에서 실측으로 튜닝된 임계값이라 재검증 없이 그대로 재사용한다. 다만
얼굴 흐림 판단은 PicMedic-Web에 없는 이 앱만의 기능이다: core/face_restorer.py가
이미 받아둔 facexlib 얼굴 탐지 모델(RestoreFormer++ 체크포인트는 로드하지
않음, 탐지만 가벼움)로 얼굴을 찾고, 각 얼굴 크롭에 같은 블러 공식을 적용한다.

torch/facexlib는 이 파일 최상단이 아니라 함수 안에서 지연 import한다 —
core/face_restorer.py·core/deblur.py와 같은 이유(앱 시작 속도). Pillow 쪽
검사는 이 앱이 이미 항상 쓰는 의존성이라 지연시킬 이유가 없다.

이 기능은 사용자 요청으로 폴더 스캔(core/scanner.py)이 아니라 상세 화면에서
사진 한 장을 열었을 때만 실행한다 — 대량 폴더 검사 속도에 영향을 주지 않기
위함(2026-09-06 논의). 배치 버전은 만들지 않는다 — "한 장만" 되게 하라는
명시적 요청.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageFilter, ImageStat

# --- PicMedic-Web/core/diagnosis.py에서 그대로 포팅 (실측 튜닝된 임계값) ---
QUALITY_ANALYSIS_MAX_SIDE = 512
BLUR_EDGE_VARIANCE_THRESHOLD = 400.0
DARK_MEAN_THRESHOLD = 50.0
BRIGHT_MEAN_THRESHOLD = 205.0
LOW_CONTRAST_STDDEV_THRESHOLD = 20.0
NOISE_CROP_SIZE = 400
NOISE_RESIDUAL_STDDEV_THRESHOLD = 5.0

# 총 픽셀 수 100만(예: 1000x1000) 미만이면 저해상도로 본다.
LOW_RESOLUTION_PIXEL_THRESHOLD = 1_000_000

# 얼굴 크롭에 블러 공식을 적용할 때 최소 크기 — 너무 작은 얼굴(원거리 인물)은
# 애초에 디테일이 적어 edge variance가 낮게 나오는 게 자연스러워 오탐이 심하다.
MIN_FACE_CROP_SIZE = 60


def _center_crop(img: Image.Image, size: int) -> Image.Image:
    w, h = img.size
    cw, ch = min(size, w), min(size, h)
    left = (w - cw) // 2
    top = (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def _edge_variance(gray: Image.Image) -> float:
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).var[0]


def assess_quality_issues(path: str | Path) -> list[str]:
    """블러/노출/저대비/노이즈를 그레이스케일 통계로 추정한다. 실패하면 조용히
    빈 목록(PicMedic-Web/core/diagnosis.py::assess_quality_issues와 동일)."""
    issues: list[str] = []
    try:
        with Image.open(path) as img:
            full_gray = img.convert("L")

            noise_sample = _center_crop(full_gray, NOISE_CROP_SIZE)
            denoised = noise_sample.filter(ImageFilter.MedianFilter(size=3))
            residual = ImageChops.difference(noise_sample, denoised)
            noise_stddev = ImageStat.Stat(residual).stddev[0]

            gray = full_gray.copy()
            gray.thumbnail((QUALITY_ANALYSIS_MAX_SIDE, QUALITY_ANALYSIS_MAX_SIDE))

            brightness = ImageStat.Stat(gray)
            mean = brightness.mean[0]
            stddev = brightness.stddev[0]

            edge_variance = _edge_variance(gray)

            if edge_variance < BLUR_EDGE_VARIANCE_THRESHOLD:
                issues.append("블러 추정")
            if mean < DARK_MEAN_THRESHOLD:
                issues.append("노출 부족 추정")
            elif mean > BRIGHT_MEAN_THRESHOLD:
                issues.append("노출 과다 추정")
            if stddev < LOW_CONTRAST_STDDEV_THRESHOLD:
                issues.append("저대비 추정")
            if noise_stddev > NOISE_RESIDUAL_STDDEV_THRESHOLD:
                issues.append("노이즈 추정")
    except Exception:
        pass
    return issues


def is_low_resolution(width: int | None, height: int | None) -> bool:
    if not width or not height:
        return False
    return width * height < LOW_RESOLUTION_PIXEL_THRESHOLD


_detection_model_cache = None  # (model, device) 캐시 — 세션 중 반복 호출 시 재로딩 방지


def _get_detection_model(weights_dir: Path):
    """facexlib 얼굴 탐지 모델을 지연 생성하고 캐싱한다(모듈 전역, 프로세스
    수명 동안 재사용). 원래 매 diagnose_photo() 호출마다 새로 만들고 있었는데
    — 이게 "진단마다 몇 초씩 느리고 그 동안 취소도 안 먹는다"는 문제의 실제
    원인이었다(2026-09-07, 사용자가 겪은 현상 보고 후 발견). core/face_restorer.py
    ::_get_restorer()와 같은 패턴."""
    global _detection_model_cache
    if _detection_model_cache is not None:
        return _detection_model_cache

    import torch
    from facexlib.detection import init_detection_model

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = init_detection_model("retinaface_resnet50", half=False, device=device, model_rootpath=str(weights_dir))
    _detection_model_cache = (model, device)
    return _detection_model_cache


def detect_faces(
    path: str | Path, *, should_cancel: Callable[[], bool] | None = None
) -> list[tuple[int, int, int, int]]:
    """얼굴 위치만 찾는다(각 얼굴이 개별적으로 흐린지는 판단하지 않음 — 아래
    참고). facexlib 자산이 없으면 빈 목록.

    원래는 얼굴 크롭마다 assess_quality_issues()와 같은 edge-variance 공식으로
    "이 얼굴이 흐린지"까지 따로 판단하려 했는데, 실측해보니 안 먹혔다: 같은
    사진에 인위적으로 blur radius를 0→10까지 늘려가며 얼굴 크롭의 edge
    variance를 찍어봐도 값이 단조 감소하지 않았다(크롭이 작아서 리사이즈
    보간·JPEG 압축 잡음이 실제 블러 신호보다 더 크게 작용하는 것으로 보임) —
    전체 이미지를 512px로 축소해서 재는 assess_quality_issues()의 방식은
    안정적으로 작동하는데, 그 방식을 훨씬 작은 얼굴 크롭에 그대로 적용하면
    재현이 안 됐다는 뜻. 잘못된 "얼굴 선명함/흐림" 판정을 내리는 것보다,
    "얼굴이 있다 + 사진 전체가 흐리다"를 합쳐서 판단하는 쪽이 훨씬 신뢰할 수
    있어 이 방식으로 갔다(diagnose_photo() 참고)."""
    from core.face_restorer import _FACEXLIB_WEIGHTS_DIR

    weights_path = _FACEXLIB_WEIGHTS_DIR / "detection_Resnet50_Final.pth"
    if not weights_path.exists():
        return []

    try:
        import cv2
        import numpy as np
        import torch  # noqa: F401 - _get_detection_model()이 실제로 씀
    except ImportError:
        return []

    if should_cancel is not None and should_cancel():
        raise DiagnosisCancelled()

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return []

    # 캐시가 비어있으면(이 세션 첫 진단) 여기서 모델 로딩이 몇 초 걸릴 수
    # 있다 — 그 뒤로는 캐시라 순식간. 로딩 직후에도 취소 여부를 한 번 더
    # 확인해서, 실제 추론(더 오래 걸리는 부분) 전에 취소할 기회를 준다.
    model, device = _get_detection_model(_FACEXLIB_WEIGHTS_DIR)
    if should_cancel is not None and should_cancel():
        raise DiagnosisCancelled()

    with torch.no_grad():
        bboxes = model.detect_faces(img, 0.8)

    h, w = img.shape[:2]
    results: list[tuple[int, int, int, int]] = []
    for bbox in bboxes:
        x1, y1, x2, y2 = (int(max(0, v)) for v in bbox[:4])
        x2, y2 = min(x2, w), min(y2, h)
        if x2 - x1 >= MIN_FACE_CROP_SIZE and y2 - y1 >= MIN_FACE_CROP_SIZE:
            results.append((x1, y1, x2, y2))
    return results


@dataclass
class PhotoDiagnosis:
    quality_issues: list[str] = field(default_factory=list)  # "블러 추정" 등
    faces: list[tuple[int, int, int, int]] = field(default_factory=list)
    low_resolution: bool = False
    category: str | None = None  # "인물 사진" 등(core/photo_category.py) — 확신이 낮으면 None
    recommended_action: str | None = None  # "디블러" | "디노이즈" | "얼굴 복원" | "화질 개선" | None
    recommended_reason: str = ""


class DiagnosisCancelled(Exception):
    """사용자가 분석 중 취소를 눌렀을 때(실제 오류와 구분해서 GUI가 에러
    팝업 없이 조용히 취소 처리를 할 수 있게)."""


def diagnose_photo(
    path: str,
    width: int | None = None,
    height: int | None = None,
    *,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> PhotoDiagnosis:
    """사진 한 장을 진단하고 추천 복원 액션까지 계산한다. 배치 버전은 없다 —
    이 기능은 명시적으로 파일 하나에만 쓴다. progress_callback은 다른 AI
    기능들과 같은 (현재 단계, 전체 단계, 단계 설명) 모양. 각 단계를 "시작할
    때" 보고하고 마지막 단계(완료)만 다 끝난 뒤 보고한다 — 마지막 실제 작업
    단계를 100%로 미리 보고하면, 그 작업이 보고 *이후에* 시작돼서 진행률이
    100%인데 한참 안 끝나는 것처럼 보였다(2026-09-07, 사용자가 겪은 현상)."""

    def report(step: int, total: int, label: str):
        if progress_callback:
            progress_callback(step, total, label)

    total_steps = 4
    report(1, total_steps, "화질 분석 중")
    quality_issues = assess_quality_issues(path)

    if should_cancel is not None and should_cancel():
        raise DiagnosisCancelled()
    report(2, total_steps, "얼굴 인식 중")
    faces = detect_faces(path, should_cancel=should_cancel)

    if should_cancel is not None and should_cancel():
        raise DiagnosisCancelled()
    report(3, total_steps, "카테고리 분석 중")
    from core.photo_category import classify_photo

    category = classify_photo(path).label
    report(4, total_steps, "완료")

    low_res = is_low_resolution(width, height)

    has_blur = "블러 추정" in quality_issues

    if has_blur and faces:
        action, reason = "얼굴 복원", "얼굴이 있는 사진인데 전체적으로 흐려요 — 인물 사진엔 얼굴 복원이 디블러보다 더 잘 맞아요."
    elif has_blur:
        action, reason = "디블러", "사진 전체가 흐려요 — 디블러로 손떨림 블러를 보정해보세요."
    elif "노이즈 추정" in quality_issues:
        action, reason = "디노이즈", "노이즈(알갱이)가 보여요 — 디노이즈로 제거해보세요."
    elif low_res:
        action, reason = "화질 개선", "해상도가 낮아요 — 화질 개선으로 더 선명하게 확대해보세요."
    else:
        action, reason = None, "특별한 문제를 찾지 못했어요."

    return PhotoDiagnosis(
        quality_issues=quality_issues,
        faces=faces,
        low_resolution=low_res,
        category=category,
        recommended_action=action,
        recommended_reason=reason,
    )
