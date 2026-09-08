"""
experiments/fullframe_layout_prototype/app.py

"풀프레임" 레이아웃 프로토타입 — 본체(gui/detail_screen.py,
gui/date_organize_screen.py 등)를 직접 고치기 전에, 창을 크게 + 리사이즈
가능하게 바꿨을 때 실제로 쓸만한 느낌인지만 확인한다.

검증하려는 것 두 가지:
1. 사진 상세/뷰어 화면 — 지금은 PREVIEW_SIZE=320 고정 정사각형 미리보기다.
   QSplitter로 미리보기 영역을 창 크기에 맞춰 늘어나게 하면 어색하지 않은지,
   오른쪽 정보 패널은 고정 폭으로 둬도 괜찮은지.
2. 그리드 정리 화면 — 지금 date_organize_screen.py는 THUMB_SIZE=64 고정
   그리드다. 창을 넓히면 열 개수가 늘어나서 한 번에 더 많은 사진이 보이는
   게 실제로 체감되는지, 몇 열까지 늘어나면 오히려 사진이 너무 작아 보이는지.

새 의존성 없음 — city_organize_prototype과 달리 별도 venv가 필요 없다(PySide6는
이미 본체의 핵심 의존성이라 여기서만 따로 설치할 이유가 없음). 그래서
gui/theme.py의 실제 COLORS/APP_STYLESHEET를 그대로 import해서 색감은 본체와
동일하게 맞췄다 — 레이아웃 구조만 확인하면 되는 프로토타입이라 사진 자리에는
실제 파일 대신 크기가 눈에 보이는 placeholder를 그린다.

실행: 저장소 루트에서 (본체와 같은 venv)
    python experiments/fullframe_layout_prototype/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.theme import APP_STYLESHEET, COLORS

_THUMB_SIZE = 150
_THUMB_SPACING = 12
_GRID_MARGIN = 24


class _SizeAwarePreview(QFrame):
    """실제 사진 대신, 지금 렌더링되는 크기를 그대로 보여주는 placeholder.
    창을 늘렸을 때 미리보기 영역이 실제로 얼마나 커지는지 숫자로 바로
    확인하기 위한 것 — 리사이즈마다 값이 바뀌는 걸 눈으로 봐야 의미가 있다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor(COLORS["selection"]))
        gradient.setColorAt(1.0, QColor(COLORS["primary"]))
        painter.fillRect(rect, gradient)

        painter.setPen(QColor("#FFFFFF"))
        font = painter.font()
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{rect.width()} × {rect.height()}px\n(실제 사진 자리)")
        painter.end()


def _category_row(label: str, color: str, glyph: str, count: int) -> QFrame:
    row = QFrame()
    row.setObjectName("Card")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(14, 11, 14, 11)
    layout.setSpacing(12)

    dot = QLabel(glyph)
    dot.setFixedSize(26, 26)
    dot.setAlignment(Qt.AlignCenter)
    dot.setStyleSheet(
        f"background-color: {color}; color: white; border-radius: 13px; font-weight: 700;"
    )
    layout.addWidget(dot)

    text = QLabel(label)
    text.setStyleSheet("font-weight: 600;")
    layout.addWidget(text, stretch=1)

    n = QLabel(f"{count}장")
    n.setStyleSheet(f"color: {COLORS['text_secondary']};")
    layout.addWidget(n)
    return row


def _build_detail_screen() -> QWidget:
    """후보 1: 사진 상세/뷰어 — QSplitter로 미리보기만 늘어나게."""
    root = QWidget()
    outer = QVBoxLayout(root)
    outer.setContentsMargins(20, 20, 20, 20)

    splitter = QSplitter(Qt.Horizontal)

    preview = _SizeAwarePreview()
    splitter.addWidget(preview)

    panel = QFrame()
    panel.setObjectName("Card")
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(20, 20, 20, 20)
    panel_layout.setSpacing(10)

    title = QLabel("IMG_0231.HEIC")
    title.setObjectName("Title")
    title.setStyleSheet("font-size: 17px; font-weight: 700;")
    panel_layout.addWidget(title)

    sub = QLabel("2025-08-14 촬영 · 4.2MB")
    sub.setObjectName("Subtitle")
    panel_layout.addWidget(sub)

    panel_layout.addSpacing(8)
    panel_layout.addWidget(_category_row("이 파일 상태: 정상", COLORS["success"], "✓", 1))
    panel_layout.addStretch(1)

    btn_row = QHBoxLayout()
    restore_btn = QPushButton("실제 형식으로 복구")
    convert_btn = QPushButton("확장자 변환")
    convert_btn.setObjectName("Primary")
    btn_row.addWidget(restore_btn)
    btn_row.addWidget(convert_btn)
    panel_layout.addLayout(btn_row)

    panel.setMinimumWidth(300)
    panel.setMaximumWidth(420)
    splitter.addWidget(panel)

    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 0)
    splitter.setSizes([900, 340])

    outer.addWidget(splitter)
    return root


class _ReflowGrid(QScrollArea):
    """후보 2: 그리드 정리 — 창 너비에 맞춰 열 개수를 다시 계산한다."""

    def __init__(self, count_label: QLabel, parent=None):
        super().__init__(parent)
        self._count_label = count_label
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(_GRID_MARGIN, _GRID_MARGIN, _GRID_MARGIN, _GRID_MARGIN)
        self._grid.setSpacing(_THUMB_SPACING)
        self.setWidget(self._container)

        self._tiles: list[QFrame] = []
        for i in range(42):
            self._tiles.append(self._make_tile(i))

        self._relayout()

    def _make_tile(self, index: int) -> QFrame:
        tile = QFrame()
        tile.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        if index % 11 == 0:
            style = f"background-color: {COLORS['selection']}; border-radius: 10px; border: 3px solid {COLORS['primary']};"
            badge = "✓"
            badge_color = COLORS["primary"]
        elif index % 7 == 0:
            style = f"background-color: {COLORS['border']}; border-radius: 10px; opacity: 0.4;"
            badge = ""
            badge_color = COLORS["muted"]
        else:
            style = f"background-color: {COLORS['border']}; border-radius: 10px;"
            badge = ""
            badge_color = ""
        tile.setStyleSheet(style)

        if badge:
            inner = QVBoxLayout(tile)
            inner.setContentsMargins(0, 0, 8, 8)
            inner.setAlignment(Qt.AlignBottom | Qt.AlignRight)
            mark = QLabel(badge)
            mark.setFixedSize(20, 20)
            mark.setAlignment(Qt.AlignCenter)
            mark.setStyleSheet(
                f"background-color: {badge_color}; color: white; border-radius: 10px; font-weight: 700;"
            )
            inner.addWidget(mark)
        return tile

    def _relayout(self) -> None:
        available = max(self.viewport().width() - 2 * _GRID_MARGIN, _THUMB_SIZE)
        columns = max(1, (available + _THUMB_SPACING) // (_THUMB_SIZE + _THUMB_SPACING))

        while self._grid.count():
            self._grid.takeAt(0)

        for idx, tile in enumerate(self._tiles):
            row, col = divmod(idx, columns)
            self._grid.addWidget(tile, row, col)

        visible_rows = max(1, self.viewport().height() // (_THUMB_SIZE + _THUMB_SPACING))
        visible_count = min(len(self._tiles), columns * visible_rows)
        self._count_label.setText(
            f"창 너비 {self.viewport().width()}px → {columns}열, 스크롤 없이 약 {visible_count}장 보임"
            f" (전체 {len(self._tiles)}장)"
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout()


def _build_grid_screen() -> QWidget:
    root = QWidget()
    outer = QVBoxLayout(root)
    outer.setContentsMargins(20, 20, 20, 0)
    outer.setSpacing(8)

    bar = QHBoxLayout()
    date_label = QLabel("2025년 8월 14일 · 부산  ·  유사 사진 42장")
    date_label.setStyleSheet("font-weight: 700; font-size: 14px;")
    bar.addWidget(date_label)
    bar.addStretch(1)
    outer.addLayout(bar)

    count_label = QLabel()
    count_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    outer.addWidget(count_label)

    grid = _ReflowGrid(count_label)
    outer.addWidget(grid, stretch=1)
    return root


class PrototypeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("풀프레임 레이아웃 프로토타입 — 창을 늘려/줄여보세요")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        switch_bar = QFrame()
        switch_bar.setStyleSheet(f"background-color: {COLORS['surface']}; border-bottom: 1px solid {COLORS['border']};")
        switch_layout = QHBoxLayout(switch_bar)
        switch_layout.setContentsMargins(20, 12, 20, 12)

        note = QLabel("풀프레임 후보 — 검사 결과 화면에서 넘어가는 게 아니라 여기서만 확인용")
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px;")
        switch_layout.addWidget(note)
        switch_layout.addStretch(1)

        btn_a = QPushButton("① 사진 상세 (Splitter)")
        btn_b = QPushButton("② 그리드 정리 (Reflow)")
        switch_layout.addWidget(btn_a)
        switch_layout.addWidget(btn_b)
        outer.addWidget(switch_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(_build_detail_screen())
        self.stack.addWidget(_build_grid_screen())
        outer.addWidget(self.stack, stretch=1)

        btn_a.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        btn_b.clicked.connect(lambda: self.stack.setCurrentIndex(1))


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    window = PrototypeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
