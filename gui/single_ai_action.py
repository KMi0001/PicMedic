"""
gui/single_ai_action.py

"얼굴 복원"/"디블러"/"디노이즈" 셋 다 사진 한 장 → 확인 팝업(예상 소요 시간
안내) → 모달 ProgressDialog(단계 기반 진행률) → 원본/결과 2분할 결과 안내,
라는 완전히 같은 흐름이었다(gui/deblur_dialog.py·denoise_dialog.py가 클래스
이름만 다르고 나머지는 1:1로 동일했음 — 2026-09-07, 사용자 요청으로 공용화).
"화질 개선"(bicubic-vs-AI 4분할 비교가 필요해 구조가 다름)과 "사진 진단"
(이미지 비교 자체가 없음)은 그대로 별도 파일로 둔다 — 억지로 여기 끼워맞추면
조건분기만 늘어난다.

각 기능은 SingleAIActionConfig 하나로 차이(제목/문구/실행 함수/예외 종류/시간
추정)만 넘기고, 나머지 다이얼로그 코드는 이 파일에 한 번만 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.common_dialogs import info_dialog, question_icon_pixmap, ProgressDialog
from gui.theme import COLORS
from gui.thumbnail import load_thumbnail

_COMPARE_BOX_SIZE = 220


@dataclass
class SingleAIActionConfig:
    title: str  # "디블러" / "디노이즈" / "얼굴 복원" — 팝업 제목에 그대로 들어감
    start_label: str  # "디블러 시작"
    confirm_message_lines: list[str]  # 시간 추정 앞에 항상 보여줄 고정 안내문
    result_box_label: str  # 결과 이미지 칸 캡션 — "보정 결과" / "복원 결과"
    is_available: Callable[[], bool]
    unavailable_message: str
    run_action: Callable[..., str]  # (input_path, output_dir, *, progress_callback, should_cancel) -> str
    cancelled_exception: type
    estimate_range: Callable[[Optional[int], Optional[int]], Optional[tuple]]  # (w,h) -> (낮,높음) 초 | None
    no_effect_exception: type | None = None  # 예: face_restorer.NoFaceFoundError
    no_effect_message: str | None = None


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{round(seconds)}초"
    return f"{seconds / 60:.1f}분"


def _confirm(parent: QWidget, config: SingleAIActionConfig, width: int | None, height: int | None) -> bool:
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")
    dialog.setWindowModality(Qt.WindowModal)

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(question_icon_pixmap(COLORS["primary"]))
    layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    message_lines = list(config.confirm_message_lines)
    estimate = config.estimate_range(width, height)
    if estimate is not None:
        low, high = estimate
        message_lines += ["", f"<b>예상 소요 시간: 약 {_format_seconds(low)}~{_format_seconds(high)}</b>"]
        message_lines.append(
            "얼굴 수와 기기 성능에 따라 더 걸릴 수 있어요."
            if low != high
            else "기기 성능에 따라 더 걸릴 수 있어요."
        )
    msg_label = QLabel("<br>".join(message_lines))
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(300)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton(config.start_label)
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    return dialog.exec() == QDialog.Accepted


class _ResultDialog(QDialog):
    def __init__(
        self, config: SingleAIActionConfig, original_path: str, result_path: str, output_dir: str, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel(f"{config.title} 완료")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        original_pixmap = load_thumbnail(original_path, _COMPARE_BOX_SIZE)
        result_pixmap = load_thumbnail(result_path, _COMPARE_BOX_SIZE)
        grid.addWidget(self._make_box("원본", original_pixmap), 0, 0)
        grid.addWidget(self._make_box(config.result_box_label, result_pixmap), 0, 1)
        layout.addLayout(grid)

        path_label = QLabel(f"저장 위치: {result_path}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px;")
        layout.addWidget(path_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        open_folder_btn = QPushButton("폴더 열기")
        open_folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(output_dir)))
        btn_row.addWidget(open_folder_btn)
        close_btn = QPushButton("확인")
        close_btn.setObjectName("Primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _make_box(self, title: str, pixmap) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        box_layout = QVBoxLayout(frame)
        caption = QLabel(title)
        caption.setStyleSheet("font-weight: 600; font-size: 11.5px;")
        caption.setAlignment(Qt.AlignCenter)
        box_layout.addWidget(caption)

        image_label = QLabel()
        image_label.setFixedSize(_COMPARE_BOX_SIZE, _COMPARE_BOX_SIZE)
        image_label.setAlignment(Qt.AlignCenter)
        if pixmap is not None:
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("미리보기 없음")
            image_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        box_layout.addWidget(image_label)
        return frame


class _Worker(QThread):
    progress = Signal(int, int, str)
    succeeded = Signal(str)
    no_effect = Signal()
    failed = Signal(str)

    def __init__(self, config: SingleAIActionConfig, input_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self._config = config
        self._input_path = input_path
        self._output_dir = output_dir
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            result_path = self._config.run_action(
                self._input_path,
                self._output_dir,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except self._config.cancelled_exception:
            return  # 취소는 에러가 아니므로 조용히 끝낸다
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            if self._config.no_effect_exception is not None and isinstance(exc, self._config.no_effect_exception):
                self.no_effect.emit()
            else:
                self.failed.emit(str(exc))
            return
        self.succeeded.emit(result_path)


def run_single_ai_action(
    parent: QWidget,
    path: str,
    config: SingleAIActionConfig,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """path 사진에 config가 가리키는 AI 기능을 실행한다 — 확인 팝업부터 결과
    안내까지 전부 처리."""
    if not config.is_available():
        info_dialog(parent, config.unavailable_message)
        return

    if not _confirm(parent, config, width, height):
        return

    output_dir = str(Path(path).parent / "Enhanced")
    progress_dialog = ProgressDialog(parent)
    worker = _Worker(config, path, output_dir, parent)

    def on_progress(step: int, total: int, label: str):
        progress_dialog.update_progress(step, total, label)

    def on_succeeded(result_path: str):
        progress_dialog.accept()
        result_dialog = _ResultDialog(config, path, result_path, output_dir, parent)
        result_dialog.exec()

    def on_no_effect():
        progress_dialog.accept()
        info_dialog(parent, config.no_effect_message or f"{config.title}에 실패했습니다.")

    def on_failed(message: str):
        progress_dialog.accept()
        info_dialog(parent, f"{config.title}에 실패했습니다:\n{message}")

    def on_finished():
        if progress_dialog.isVisible():
            progress_dialog.accept()

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_succeeded)
    worker.no_effect.connect(on_no_effect)
    worker.failed.connect(on_failed)
    worker.finished.connect(on_finished)

    progress_dialog.start(f"{config.title} 중")
    worker.start()
    progress_dialog.exec()
