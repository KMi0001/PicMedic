"""
gui/denoise_dialog.py

"디노이즈"(core/denoise.py) 실행 흐름 — gui/single_ai_action.py의 공용 확인→
진행→결과 다이얼로그에 이 기능만의 문구/함수를 config로 넘긴다. 원래
"디블러/디노이즈" 하나였다가, NAFNet의 디블러/디노이즈 가중치가 서로 다른
데이터셋으로 학습된 별도 모델이라(core/denoise.py 상단 설명 참고) 기능을
분리했다.

gui/deblur_dialog.py와 같은 이유로 core/denoise.py의 사전/사후 안전장치
(DenoiseNotRecommendedError·DenoiseResultUnstableError)를 no_effect_exception에
걸어둔다 — 망가진 결과를 사용자에게 아예 보여주지 않는다.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core import denoise
from gui.single_ai_action import run_single_ai_action, SingleAIActionConfig

_CONFIG = SingleAIActionConfig(
    title="디노이즈",
    start_label="디노이즈 시작",
    confirm_message_lines=[
        "야간 촬영 등에서 생기는 노이즈(알갱이)를 줄여요.",
        "인물이 없는 풍경/사물 사진에도 적용돼요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
    ],
    result_box_label="보정 결과",
    is_available=denoise.is_available,
    unavailable_message="이 기기에서는 디노이즈 기능을 쓸 수 없습니다.",
    run_action=denoise.denoise_image,
    cancelled_exception=denoise.DenoiseCancelled,
    estimate_range=lambda w, h: (denoise.estimate_seconds(w, h),) * 2 if w and h else None,
    no_effect_exception=(denoise.DenoiseNotRecommendedError, denoise.DenoiseResultUnstableError),
)


def run_denoise(parent: QWidget, path: str, width: int | None = None, height: int | None = None) -> None:
    run_single_ai_action(parent, path, _CONFIG, width, height)
