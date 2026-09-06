"""
gui/face_restore_dialog.py

"얼굴 복원"(core/face_restorer.py) 실행 흐름 — gui/single_ai_action.py의
공용 확인→진행→결과 다이얼로그에 이 기능만의 문구/함수를 config로 넘긴다.
다른 둘과 다른 점: 예상 소요 시간이 해상도가 아니라 얼굴 수 기반 범위라
estimate_range가 width/height를 무시하고 항상 같은 범위를 돌려주고, 얼굴을
못 찾았을 때는 실패가 아니라 "효과 없음" 안내로 처리한다(no_effect_exception).
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core import face_restorer
from gui.single_ai_action import run_single_ai_action, SingleAIActionConfig

_CONFIG = SingleAIActionConfig(
    title="얼굴 복원",
    start_label="얼굴 복원 시작",
    confirm_message_lines=[
        "사진 속 얼굴의 디테일(눈/주름/치아 등)을 AI로 복원해요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
        "",
        "\"화질 개선\"과 달리 사라진 디테일을 실제로 그려 넣는 방식이라,",
        "사람 얼굴이 없는 사진에는 효과가 없어요.",
    ],
    result_box_label="복원 결과",
    is_available=face_restorer.is_available,
    unavailable_message="이 기기에서는 얼굴 복원 기능을 쓸 수 없습니다.",
    run_action=face_restorer.restore_face,
    cancelled_exception=face_restorer.FaceRestorationCancelled,
    estimate_range=lambda w, h: face_restorer.estimate_seconds_range(),
    no_effect_exception=face_restorer.NoFaceFoundError,
    no_effect_message="사진에서 얼굴을 찾지 못해 복원할 수 없습니다.",
)


def run_face_restoration(parent: QWidget, path: str) -> None:
    run_single_ai_action(parent, path, _CONFIG)
