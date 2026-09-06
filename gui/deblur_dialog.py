"""
gui/deblur_dialog.py

"디블러"(core/deblur.py) 실행 흐름 — gui/single_ai_action.py의 공용 확인→
진행→결과 다이얼로그에 이 기능만의 문구/함수를 config로 넘긴다.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core import deblur
from gui.single_ai_action import run_single_ai_action, SingleAIActionConfig

_CONFIG = SingleAIActionConfig(
    title="디블러",
    start_label="디블러 시작",
    confirm_message_lines=[
        "손떨림 블러가 있는 사진을 보정해요.",
        "얼굴 복원과 달리 인물이 없는 사진에도 적용돼요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
    ],
    result_box_label="보정 결과",
    is_available=deblur.is_available,
    unavailable_message="이 기기에서는 디블러 기능을 쓸 수 없습니다.",
    run_action=deblur.deblur_image,
    cancelled_exception=deblur.DeblurCancelled,
    estimate_range=lambda w, h: (deblur.estimate_seconds(w, h),) * 2 if w and h else None,
)


def run_deblur(parent: QWidget, path: str, width: int | None = None, height: int | None = None) -> None:
    run_single_ai_action(parent, path, _CONFIG, width, height)
