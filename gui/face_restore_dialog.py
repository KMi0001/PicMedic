"""
gui/face_restore_dialog.py

"얼굴 복원"(core/face_restorer.py) 실행 흐름 — 확인 팝업(예상 소요 시간 +
"화질 개선"과 다르다는 안내) → 진행 팝업(단계 기반) → 결과 안내까지 한 번에
처리한다. gui/quality_enhance_dialog.py와 같은 구조지만, 이건 확대가 아니라서
"단순 확대 vs AI" 크롭 비교 없이 원본/결과 전체 2분할로 충분하다.
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

from core import face_restorer
from gui.common_dialogs import info_dialog, question_icon_pixmap, ProgressDialog
from gui.theme import COLORS
from gui.thumbnail import load_thumbnail

_COMPARE_BOX_SIZE = 220


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{round(seconds)}초"
    return f"{seconds / 60:.1f}분"


def _confirm_restore(parent: QWidget) -> bool:
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
    low, high = face_restorer.estimate_seconds_range()
    message_lines = [
        "사진 속 얼굴의 디테일(눈/주름/치아 등)을 AI로 복원해요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
        "",
        "\"화질 개선\"과 달리 사라진 디테일을 실제로 그려 넣는 방식이라,",
        "사람 얼굴이 없는 사진에는 효과가 없어요.",
        "",
        f"<b>예상 소요 시간: 약 {_format_seconds(low)}~{_format_seconds(high)}</b>",
        "얼굴 수와 기기 성능에 따라 더 걸릴 수 있어요.",
    ]
    msg_label = QLabel("<br>".join(message_lines))
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(300)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton("얼굴 복원 시작")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    return dialog.exec() == QDialog.Accepted


class _RestoreResultDialog(QDialog):
    """완료 후 원본/복원 결과를 나란히 보여준다."""

    def __init__(self, original_path: str, result_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("얼굴 복원 완료")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        original_pixmap = load_thumbnail(original_path, _COMPARE_BOX_SIZE)
        result_pixmap = load_thumbnail(result_path, _COMPARE_BOX_SIZE)
        grid.addWidget(self._make_box("원본", original_pixmap), 0, 0)
        grid.addWidget(self._make_box("복원 결과", result_pixmap), 0, 1)
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


class _RestoreWorker(QThread):
    """core/face_restorer.restore_face()는 모델 로딩+추론으로 수 초~수십 초
    걸리고 첫 실행 시 PyTorch 초기화까지 겹쳐 더 걸릴 수 있는 블로킹 호출이라,
    별도 스레드로 돌린다(quality_enhance_dialog.py의 _EnhanceWorker와 동일한
    이유)."""

    progress = Signal(int, int, str)
    succeeded = Signal(str)
    no_face = Signal()
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
            result_path = face_restorer.restore_face(
                self._input_path,
                self._output_dir,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except face_restorer.FaceRestorationCancelled:
            return  # 취소는 에러가 아니므로 조용히 끝낸다
        except face_restorer.NoFaceFoundError:
            self.no_face.emit()
            return
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result_path)


def run_face_restoration(parent: QWidget, path: str) -> None:
    """path 사진의 얼굴을 복원한다 — 확인 팝업부터 결과 안내까지 전부 처리."""
    if not face_restorer.is_available():
        info_dialog(parent, "이 기기에서는 얼굴 복원 기능을 쓸 수 없습니다.")
        return

    if not _confirm_restore(parent):
        return

    output_dir = str(Path(path).parent / "Enhanced")
    progress_dialog = ProgressDialog(parent)
    worker = _RestoreWorker(path, output_dir, parent)

    def on_progress(step: int, total: int, label: str):
        progress_dialog.update_progress(step, total, label)

    def on_succeeded(result_path: str):
        progress_dialog.accept()
        result_dialog = _RestoreResultDialog(path, result_path, output_dir, parent)
        result_dialog.exec()

    def on_no_face():
        progress_dialog.accept()
        info_dialog(parent, "사진에서 얼굴을 찾지 못해 복원할 수 없습니다.")

    def on_failed(message: str):
        progress_dialog.accept()
        info_dialog(parent, f"얼굴 복원에 실패했습니다:\n{message}")

    def on_finished():
        if progress_dialog.isVisible():
            progress_dialog.accept()

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_succeeded)
    worker.no_face.connect(on_no_face)
    worker.failed.connect(on_failed)
    worker.finished.connect(on_finished)

    progress_dialog.start("얼굴 복원 중")
    worker.start()
    progress_dialog.exec()
