"""
gui/denoise_dialog.py

"디노이즈"(core/denoise.py) 실행 흐름 — gui/deblur_dialog.py와 완전히 같은
구조(확인 팝업 → 진행 팝업 → 원본/결과 2분할 결과 안내). 원래 "디블러/
디노이즈" 하나였다가, NAFNet의 디블러/디노이즈 가중치가 서로 다른 데이터셋으로
학습된 별도 모델이라(core/denoise.py 상단 설명 참고) 기능을 분리했다.
"""

from __future__ import annotations

from pathlib import Path

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

from core import denoise
from gui.common_dialogs import info_dialog, question_icon_pixmap, ProgressDialog
from gui.theme import COLORS
from gui.thumbnail import load_thumbnail

_COMPARE_BOX_SIZE = 220


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{round(seconds)}초"
    return f"{seconds / 60:.1f}분"


def _confirm_denoise(parent: QWidget, width: int | None, height: int | None) -> bool:
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
    message_lines = [
        "야간 촬영 등에서 생기는 노이즈(알갱이)를 줄여요.",
        "인물이 없는 풍경/사물 사진에도 적용돼요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
    ]
    if width and height:
        seconds = denoise.estimate_seconds(width, height)
        message_lines += [
            "",
            f"<b>예상 소요 시간: 약 {_format_seconds(seconds)}</b>",
            "기기 성능에 따라 더 걸릴 수 있어요.",
        ]
    msg_label = QLabel("<br>".join(message_lines))
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(300)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton("디노이즈 시작")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    return dialog.exec() == QDialog.Accepted


class _DenoiseResultDialog(QDialog):
    def __init__(self, original_path: str, result_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("디노이즈 완료")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        original_pixmap = load_thumbnail(original_path, _COMPARE_BOX_SIZE)
        result_pixmap = load_thumbnail(result_path, _COMPARE_BOX_SIZE)
        grid.addWidget(self._make_box("원본", original_pixmap), 0, 0)
        grid.addWidget(self._make_box("보정 결과", result_pixmap), 0, 1)
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


class _DenoiseWorker(QThread):
    progress = Signal(int, int, str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, input_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self._input_path = input_path
        self._output_dir = output_dir
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            result_path = denoise.denoise_image(
                self._input_path,
                self._output_dir,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except denoise.DenoiseCancelled:
            return
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result_path)


def run_denoise(parent: QWidget, path: str, width: int | None = None, height: int | None = None) -> None:
    """path 사진을 디노이즈한다 — 확인 팝업부터 결과 안내까지 전부 처리."""
    if not denoise.is_available():
        info_dialog(parent, "이 기기에서는 디노이즈 기능을 쓸 수 없습니다.")
        return

    if not _confirm_denoise(parent, width, height):
        return

    output_dir = str(Path(path).parent / "Enhanced")
    progress_dialog = ProgressDialog(parent)
    worker = _DenoiseWorker(path, output_dir, parent)

    def on_progress(step: int, total: int, label: str):
        progress_dialog.update_progress(step, total, label)

    def on_succeeded(result_path: str):
        progress_dialog.accept()
        result_dialog = _DenoiseResultDialog(path, result_path, output_dir, parent)
        result_dialog.exec()

    def on_failed(message: str):
        progress_dialog.accept()
        info_dialog(parent, f"디노이즈에 실패했습니다:\n{message}")

    def on_finished():
        if progress_dialog.isVisible():
            progress_dialog.accept()

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_succeeded)
    worker.failed.connect(on_failed)
    worker.finished.connect(on_finished)

    progress_dialog.start("디노이즈 중")
    worker.start()
    progress_dialog.exec()
