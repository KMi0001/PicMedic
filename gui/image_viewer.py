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

from PySide6.QtCore import Qt, QSize, QTimer, Signal
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


# overlay_controls=True일 때 사진 위에 얹는 반투명 알약 툴바 스타일
# (experiments/viewer_redesign_prototype에서 확인 후 반영, 2026-09-08).
_OVERLAY_TOOLBAR_STYLESHEET = (
    "QWidget#ViewerOverlayToolbar {"
    " background-color: rgba(20, 18, 15, 150);"
    " border-radius: 16px;"
    "}"
    "QToolButton {"
    " background: transparent;"
    " border: none;"
    " color: white;"
    "}"
    "QToolButton:hover {"
    " background-color: rgba(255, 255, 255, 40);"
    " border-radius: 8px;"
    "}"
    "QToolButton:disabled {"
    " color: rgba(255, 255, 255, 90);"
    "}"
)


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

    def sizeHint(self) -> QSize:
        # QGraphicsView의 기본 sizeHint()는 씬(scene) 내용 크기를 따라간다 —
        # 원본 해상도 그대로(예: 4000x3000) 큰 사진을 넣으면 이 위젯의 "선호
        # 크기"가 그만큼 커지고, 그게 레이아웃을 타고 올라가 최상위 창의 크기
        # 계산에 반영된다. 그 상태로 창 테두리를 드래그하면(매 리사이즈 이벤트마다
        # 레이아웃이 다시 계산되며 이 큰 sizeHint를 반영하려다) 창이 매끄럽게
        # 안 늘고 위아래로 훅훅 붙어버리는 문제가 있었다(2026-09-08, 사용자
        # 리포트) — 사진 크기와 무관하게 항상 작고 고정된 값을 돌려줘서, 실제
        # 표시 크기는 (여기 sizeHint가 아니라) 부모가 배분해주는 크기와
        # fit_to_view()에 온전히 맡긴다.
        return QSize(200, 150)

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
    맞춰 보여주고, 휠 확대/축소·드래그 이동·버튼 회전을 지원한다.

    overlay_controls=True면 회전/맞추기 버튼을 별도 줄 없이 사진 위에 반투명
    알약 모양으로 겹쳐서 보여준다(gui/result_screen.py 인라인 미리보기 —
    "틀 없이 사진을 중앙에, 버튼은 사진 안쪽에 살짝 투명하게" 요청, 2026-09-08,
    experiments/viewer_redesign_prototype에서 방향 확인 후 반영). 기본값
    False는 기존처럼 위쪽에 고정된 버튼 줄을 쓴다(gui/detail_screen.py 등
    다른 화면은 그대로 둠 — 요청 범위가 검사결과 인라인 미리보기였음)."""

    def __init__(
        self,
        parent=None,
        placeholder_text: str = "미리보기를 생성할 수 없습니다.",
        overlay_controls: bool = False,
    ):
        super().__init__(parent)
        self._rotation = 0
        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._user_zoomed = False
        self._overlay_controls = overlay_controls

        # 창 테두리를 드래그해 라이브 리사이즈하는 동안 resizeEvent가 초당
        # 수십 번씩 온다 — 원본 해상도 그대로(축소 없이) 들고 있는 큰 사진에서
        # 매번 fit_to_view()(스무스 변환 다시 계산)를 동기로 돌리면 그 처리가
        # 밀려서, 이 뷰어를 켜둔 채로 창을 드래그하면 창이 매끄럽게 안 늘고
        # 한 번에 훅 튀어 보이는 문제가 있었다(2026-09-08, 사용자 리포트).
        # 리사이즈가 잠깐 멈췄을 때만(짧은 디바운스) 실제로 다시 맞추도록 미룬다.
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(80)
        self._refit_timer.timeout.connect(self.fit_to_view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._rotate_left_btn = _tool_button("⟲", "왼쪽으로 90도 회전")
        self._rotate_right_btn = _tool_button("⟳", "오른쪽으로 90도 회전")
        self._fit_btn = _tool_button("⤢", "화면에 맞추기")
        self._rotate_left_btn.clicked.connect(lambda: self._rotate(-90))
        self._rotate_right_btn.clicked.connect(lambda: self._rotate(90))
        self._fit_btn.clicked.connect(self.fit_to_view)

        self._overlay_toolbar: Optional[QWidget] = None
        if overlay_controls:
            # 별도 줄이 아니라 사진 위에 떠 있는 위젯으로 — 일반 레이아웃에
            # 안 넣고 self를 부모로 둔 채 resizeEvent에서 직접 위치를 잡는다.
            self._overlay_toolbar = QWidget(self)
            self._overlay_toolbar.setObjectName("ViewerOverlayToolbar")
            self._overlay_toolbar.setStyleSheet(_OVERLAY_TOOLBAR_STYLESHEET)
            overlay_layout = QHBoxLayout(self._overlay_toolbar)
            overlay_layout.setContentsMargins(6, 4, 6, 4)
            overlay_layout.setSpacing(2)
            for btn in (self._rotate_left_btn, self._rotate_right_btn, self._fit_btn):
                overlay_layout.addWidget(btn)
        else:
            bar = QHBoxLayout()
            bar.setSpacing(2)
            bar.addStretch(1)
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
        if self._overlay_toolbar is not None:
            self._reposition_overlay_toolbar()

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
        # QGraphicsScene.clear()는 항목만 지우지, 한 번 커진 sceneRect는 저절로
        # 안 줄어든다(Qt 기본 동작) — 큰 사진을 본 뒤 작은/다른 비율 사진으로
        # 바꾸면 예전 sceneRect 기준으로 fitInView가 중심을 잡아서 사진이
        # 가운데가 아니라 위쪽에 붙어 보이는 문제가 있었다(2026-09-08, 사용자
        # 리포트). 매번 지금 사진 크기로 sceneRect를 다시 맞춰서 방지한다.
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._stack.setCurrentWidget(self._view)
        self._set_controls_enabled(True)
        self.fit_to_view()

    def fit_to_view(self) -> None:
        if self._pixmap_item is None:
            return
        self._view.resetTransform()
        self._view.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        self._user_zoomed = False
        if self._overlay_toolbar is not None:
            self._reposition_overlay_toolbar()

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
        # 오버레이 모드에서는 사진이 없을 때(안내 문구만 있을 때) 빈 알약이
        # 둥둥 떠 있으면 어색하므로 툴바 자체를 숨긴다.
        if self._overlay_toolbar is not None:
            self._overlay_toolbar.setVisible(enabled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 사용자가 직접 확대한 뒤에는 창 크기 변화로 그 배율을 지우지 않는다.
        if self._pixmap_item is not None and not self._user_zoomed:
            self._refit_timer.start()
        if self._overlay_toolbar is not None:
            self._reposition_overlay_toolbar()

    def _reposition_overlay_toolbar(self) -> None:
        """오버레이 툴바를 실제로 사진이 그려지는 영역 하단 중앙에 겹치게
        둔다. fitInView()는 종횡비를 지키느라 뷰 안에 사진을 레터박스로
        띄우므로, 뷰 전체 영역을 기준으로 삼으면 사진이 없는 여백 아래에
        툴바가 떠 버린다 — 그래서 뷰가 아니라 사진 아이템 자체의 화면상
        경계(sceneBoundingRect를 뷰 좌표로 변환)를 기준으로 삼는다."""
        toolbar = self._overlay_toolbar
        toolbar.adjustSize()

        if self._pixmap_item is not None and self._stack.currentWidget() is self._view:
            image_rect = self._view.mapFromScene(self._pixmap_item.sceneBoundingRect()).boundingRect()
            origin = self._view.mapTo(self, image_rect.topLeft())
            area_x, area_y = origin.x(), origin.y()
            area_w, area_h = image_rect.width(), image_rect.height()
        else:
            area = self._stack.geometry()
            area_x, area_y, area_w, area_h = area.x(), area.y(), area.width(), area.height()

        x = area_x + (area_w - toolbar.width()) // 2
        y = area_y + area_h - toolbar.height() - 14
        toolbar.move(x, y)
        toolbar.raise_()
