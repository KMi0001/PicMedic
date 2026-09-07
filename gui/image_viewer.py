"""
gui/image_viewer.py

마우스 휠 확대/축소 + 드래그 이동(팬) + 좌우 90도 회전이 되는 이미지 뷰어.
보기 전용이다 — 회전/확대 상태는 화면에만 적용되고 원본 파일은 건드리지
않는다. gui/detail_screen.py(사진 상세 미리보기), gui/quality_enhance_dialog.py·
gui/single_ai_action.py(원본/결과 비교 박스) 세 곳에서 똑같이 필요해져서
공용으로 뺐다(DESIGN.md "같은 요구가 2번째로 생기면 공용 컴포넌트로 옮긴다").

QPixmap을 미리 축소해서 넣으면 확대해도 원본 디테일이 안 보이므로,
set_image_path()는 (HEIC 제외) 원본 해상도 그대로 불러온다 —
gui/thumbnail.py::load_thumbnail_qimage는 화면 목록용으로 일부러 축소해서
읽는 함수라 여기서는 쓰지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS

_HEIC_EXTENSIONS = (".heic", ".heif")  # gui/thumbnail.py::_HEIC_EXTENSIONS와 동일


def load_full_pixmap(path: str) -> Optional[QPixmap]:
    """path의 이미지를 축소 없이 원본 해상도로 불러온다. 읽을 수 없으면 None.
    gui/thumbnail.py::load_thumbnail_qimage와 같은 HEIC 예외 처리 패턴이지만
    크기를 줄이지 않는다는 점만 다르다."""
    ext = Path(path).suffix.lower()
    image: Optional[QImage] = None
    try:
        if ext in _HEIC_EXTENSIONS:
            from PIL import Image
            from PIL.ImageQt import ImageQt

            with Image.open(path) as img:
                img.load()
                image = QImage(ImageQt(img.convert("RGBA")))
        else:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            decoded = reader.read()
            if not decoded.isNull():
                image = decoded
    except Exception:
        image = None

    if image is None or image.isNull():
        return None
    return QPixmap.fromImage(image)


def _tool_button(text: str, tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(26, 22)
    return btn


class _ZoomPanView(QGraphicsView):
    """휠로 확대/축소, 기본 드래그로 이동(ScrollHandDrag)."""

    zoomed = Signal()

    _MIN_SCALE = 0.05
    _MAX_SCALE = 20.0

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)
        # 드래그로 이동하므로 스크롤바는 필요 없다 — 작은 비교 박스에서는
        # 특히 스크롤바가 그림을 가리고 지저분해 보인다.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else 1 / 1.2
        new_scale = self.transform().m11() * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self.scale(factor, factor)
            self.zoomed.emit()


class ImageViewer(QWidget):
    """set_image_path() 또는 set_pixmap()으로 이미지를 넣으면 자동으로 화면에
    맞춰 보여주고, 휠 확대/축소·드래그 이동·버튼 회전을 지원한다."""

    def __init__(self, parent=None, placeholder_text: str = "미리보기를 생성할 수 없습니다."):
        super().__init__(parent)
        self._rotation = 0
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._user_zoomed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        bar.setSpacing(2)
        bar.addStretch(1)
        self._rotate_left_btn = _tool_button("⟲", "왼쪽으로 90도 회전")
        self._rotate_right_btn = _tool_button("⟳", "오른쪽으로 90도 회전")
        self._fit_btn = _tool_button("⤢", "화면에 맞추기")
        self._rotate_left_btn.clicked.connect(lambda: self._rotate(-90))
        self._rotate_right_btn.clicked.connect(lambda: self._rotate(90))
        self._fit_btn.clicked.connect(self.fit_to_view)
        for btn in (self._rotate_left_btn, self._rotate_right_btn, self._fit_btn):
            bar.addWidget(btn)
        layout.addLayout(bar)

        self._scene = QGraphicsScene(self)
        self._view = _ZoomPanView(self._scene)
        self._view.zoomed.connect(self._on_user_zoomed)

        self._placeholder = QLabel(placeholder_text)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(f"color: {COLORS['text_secondary']};")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._placeholder)
        layout.addWidget(self._stack, stretch=1)

        self._set_controls_enabled(False)

    def set_image_path(self, path: str) -> None:
        self.set_pixmap(load_full_pixmap(path))

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._rotation = 0
        if pixmap is None or pixmap.isNull():
            self._stack.setCurrentWidget(self._placeholder)
            self._set_controls_enabled(False)
            return
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setTransformOriginPoint(self._pixmap_item.boundingRect().center())
        self._stack.setCurrentWidget(self._view)
        self._set_controls_enabled(True)
        self.fit_to_view()

    def fit_to_view(self) -> None:
        if self._pixmap_item is None:
            return
        self._view.resetTransform()
        self._view.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        self._user_zoomed = False

    def _rotate(self, delta: int) -> None:
        if self._pixmap_item is None:
            return
        self._rotation = (self._rotation + delta) % 360
        self._pixmap_item.setRotation(self._rotation)
        self.fit_to_view()

    def _on_user_zoomed(self) -> None:
        self._user_zoomed = True

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._rotate_left_btn.setEnabled(enabled)
        self._rotate_right_btn.setEnabled(enabled)
        self._fit_btn.setEnabled(enabled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 사용자가 직접 확대한 뒤에는 창 크기 변화로 그 배율을 지우지 않는다.
        if self._pixmap_item is not None and not self._user_zoomed:
            self.fit_to_view()
