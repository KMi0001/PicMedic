"""
gui/quality_enhance_dialog.py

"화질 개선"(core/quality_enhancer.py) 실행 흐름 — 확인 팝업(예상 소요 시간 +
"복구 아님" 안내) → 진행률 팝업 → 결과 안내까지 한 번에 처리한다.
gui/detail_screen.py(스캔된 파일 상세보기)와 gui/home_screen.py(스캔 없이 바로
파일 하나 선택) 둘 다에서 똑같은 흐름이 필요해져서 공용으로 뺐다(DESIGN.md
"같은 요구가 2번째로 생기면 공용 컴포넌트로 옮긴다" 원칙).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import quality_enhancer
from gui.common_dialogs import info_dialog, question_icon_pixmap, ProgressDialog
from gui.image_viewer import ImageViewer
from gui.theme import COLORS

_COMPARE_BOX_SIZE = 200
_COMPARE_CROP_SIZE = 128  # 원본 기준 크롭 한 변 길이(px) — 두 확대 방식을 공정하게 비교하기 위함


def _format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{round(seconds)}초"
    return f"{seconds / 60:.1f}분"


def _confirm_enhance(parent: QWidget, message_html: str, initial_output_dir: str) -> str | None:
    """화질 개선 확인 팝업. gui/common_dialogs.py::confirm_dialog와 같은 카드
    스타일이지만, 저장 위치를 그 자리에서 바꿀 수 있는 줄이 하나 더 있다.
    확인을 누르면 (그때 기준) 저장 위치 문자열을, 취소면 None을 반환한다."""
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
    msg_label = QLabel(message_html)
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(280)
    text_col.addWidget(msg_label)

    text_col.addSpacing(10)
    path_caption = QLabel("저장 위치")
    path_caption.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    text_col.addWidget(path_caption)

    path_row = QHBoxLayout()
    path_label = QLabel(initial_output_dir)
    path_label.setWordWrap(True)
    path_label.setFixedWidth(210)
    path_label.setStyleSheet("font-size: 12px;")
    path_row.addWidget(path_label, stretch=1)
    change_btn = QPushButton("변경")
    path_row.addWidget(change_btn)
    text_col.addLayout(path_row)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton("화질 개선 시작")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    state = {"output_dir": initial_output_dir}

    def on_change_clicked():
        chosen = QFileDialog.getExistingDirectory(dialog, "저장 위치 선택", state["output_dir"])
        if chosen:
            state["output_dir"] = chosen
            path_label.setText(chosen)

    change_btn.clicked.connect(on_change_clicked)
    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    if dialog.exec() == QDialog.Accepted:
        return state["output_dir"]
    return None


def _pil_to_pixmap(img: Image.Image, max_size: int) -> QPixmap:
    rgb = img.convert("RGB")
    qimage = QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(qimage.copy())
    return pixmap.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _build_crop_comparison(original_path: str, result_path: str, scale: int) -> tuple[QPixmap, QPixmap]:
    """같은 영역을 (1) 단순 bicubic 확대 (2) 실제 AI 업스케일 결과에서 잘라내
    같은 크기로 반환한다 — 전체 사진을 그냥 나란히 보여주면 결과도 같이
    축소되면서 디테일 차이가 없어 보이므로, "화질 차이"를 눈으로 확인하려면
    이렇게 크롭을 맞춰서 비교해야 한다(experiments/upscale_prototype에서
    확인된 방식과 동일)."""
    with Image.open(original_path) as original:
        original = original.convert("RGB")
        w, h = original.size
        cw, ch = min(_COMPARE_CROP_SIZE, w), min(_COMPARE_CROP_SIZE, h)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        original_crop = original.crop((x0, y0, x0 + cw, y0 + ch))

    baseline = original_crop.resize((cw * scale, ch * scale), Image.BICUBIC)

    with Image.open(result_path) as result:
        result = result.convert("RGB")
        rx0, ry0 = x0 * scale, y0 * scale
        result_crop = result.crop((rx0, ry0, rx0 + cw * scale, ry0 + ch * scale))

    return _pil_to_pixmap(baseline, _COMPARE_BOX_SIZE), _pil_to_pixmap(result_crop, _COMPARE_BOX_SIZE)


class _EnhanceResultDialog(QDialog):
    """완료 후 4분할로 보여주는 결과 화면 — 원본/결과 전체 썸네일 위, 같은
    영역을 공정하게 비교한 "단순 확대 vs AI 업스케일" 크롭 아래."""

    def __init__(self, original_path: str, result_path: str, scale: int, output_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("화질 개선 완료")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)

        baseline_crop_pixmap, result_crop_pixmap = _build_crop_comparison(original_path, result_path, scale)

        grid.addWidget(self._make_box("원본 (전체)", path=original_path), 0, 0)
        grid.addWidget(self._make_box("업스케일 결과 (전체)", path=result_path), 0, 1)
        grid.addWidget(self._make_box("단순 확대 (같은 영역)", pixmap=baseline_crop_pixmap), 1, 0)
        grid.addWidget(self._make_box("AI 업스케일 (같은 영역)", pixmap=result_crop_pixmap), 1, 1)
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

    def _make_box(self, title: str, *, path: str | None = None, pixmap: QPixmap | None = None) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        box_layout = QVBoxLayout(frame)
        caption = QLabel(title)
        caption.setStyleSheet("font-weight: 600; font-size: 11.5px;")
        caption.setAlignment(Qt.AlignCenter)
        box_layout.addWidget(caption)

        viewer = ImageViewer(placeholder_text="미리보기 없음")
        viewer.setFixedSize(_COMPARE_BOX_SIZE, _COMPARE_BOX_SIZE + 28)
        if path is not None:
            viewer.set_image_path(path)
        elif pixmap is not None:
            viewer.set_pixmap(pixmap)
        box_layout.addWidget(viewer)
        return frame


class _EnhanceWorker(QThread):
    """core/quality_enhancer.enhance_quality()는 수 초~1분 이상 걸릴 수 있고
    Real-ESRGAN 서브프로세스를 기다리는 블로킹 호출이라, 메인 스레드에서 그대로
    부르면 창이 "응답 없음"으로 보인다 — 별도 스레드로 돌린다."""

    progress = Signal(float)
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
            result_path = quality_enhancer.enhance_quality(
                self._input_path,
                self._output_dir,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except quality_enhancer.EnhancementCancelled:
            return  # 취소는 에러가 아니므로 failed를 쏘지 않고 조용히 끝낸다
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result_path)


def run_quality_enhancement(
    parent: QWidget,
    path: str,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """path의 사진을 화질 개선한다 — 확인 팝업부터 결과 안내까지 전부 처리.
    width/height를 알면(스캔된 파일이면) 예상 소요 시간을 같이 보여준다."""
    if not quality_enhancer.is_available():
        info_dialog(parent, "이 기기에서는 화질 개선 기능을 쓸 수 없습니다.")
        return

    message_lines = [
        "사진을 더 선명하게 확대해요.",
        "원본은 그대로 두고 새 파일로 저장돼요.",
        "",
        "사라진 디테일이 되살아나는 건 아니에요.",
        "단순 확대보다 덜 뭉개지게만 키워줘요.",
    ]
    if width and height:
        seconds = quality_enhancer.estimate_seconds(width, height)
        message_lines += [
            "",
            f"<b>예상 소요 시간: 약 {_format_seconds(seconds)}</b>",
            "그래픽카드 성능에 따라 더 걸릴 수 있어요.",
        ]
    message_html = "<br>".join(message_lines)

    initial_output_dir = str(Path(path).parent / "Enhanced")
    output_dir = _confirm_enhance(parent, message_html, initial_output_dir)
    if output_dir is None:
        return

    progress_dialog = ProgressDialog(parent)
    worker = _EnhanceWorker(path, output_dir, parent)
    filename = Path(path).name

    def on_progress(pct: float):
        progress_dialog.update_progress(int(pct), 100, filename)

    def on_succeeded(result_path: str):
        progress_dialog.accept()
        result_dialog = _EnhanceResultDialog(path, result_path, quality_enhancer.SCALE, output_dir, parent)
        result_dialog.exec()

    def on_failed(message: str):
        progress_dialog.accept()
        info_dialog(parent, f"화질 개선에 실패했습니다:\n{message}")

    def on_finished():
        if progress_dialog.isVisible():
            progress_dialog.accept()

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_succeeded)
    worker.failed.connect(on_failed)
    worker.finished.connect(on_finished)

    progress_dialog.start("화질 개선 중")
    worker.start()
    progress_dialog.exec()
