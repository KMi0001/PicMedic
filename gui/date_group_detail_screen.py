"""
gui/date_group_detail_screen.py (설계 시안 — 아직 메인 화면에 연결 안 함)

gui/date_organize_screen.py의 그룹 카드를 누르면 여는 화면. 위쪽엔 미리보기
(사진 + 파일명/메타 정보만, 액션 버튼 없음), 아래쪽엔 그 그룹 사진 전체를
썸네일 그리드로 보여준다. 목록에서 사진을 누르면 페이지 이동 없이 위쪽
미리보기가 그 사진으로 바로 바뀐다.

이 화면의 목적은 "정리"가 아니라 "확인"이다 — 사용자가 훑어보고 "아, 이런
사진들이 이 폴더로 들어가겠구나"를 알면 끝이라, 화질 개선/확장자 변환 같은
편집 액션은 일부러 넣지 않는다(그건 gui/detail_screen.py의 역할).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS
from gui.thumbnail import ClickableThumbnail, load_thumbnail
from utils.file_utils import format_file_size

THUMB_SIZE = 96
CELL_MARGIN = 8
CELL_SPACING = 12
PREVIEW_SIZE = 260


class DateGroupDetailScreen(QWidget):
    """gui/date_organize_screen.py 그룹 카드 하나를 눌렀을 때 여는 화면 —
    위: 미리보기(사진 + 이름/메타 정보만, 액션 없음), 아래: 그룹 전체 목록."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list = []
        self._cells: list[ClickableThumbnail] = []
        self._last_columns = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setObjectName("Title")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        back_btn = QPushButton("← 목록으로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        # --- 위: 미리보기(사진 왼쪽 + 이름/메타 정보 오른쪽, 액션 버튼 없음) ---
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_row = QHBoxLayout(preview_card)
        preview_row.setContentsMargins(20, 20, 20, 20)
        preview_row.setSpacing(20)

        self.preview_image = QLabel()
        self.preview_image.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setStyleSheet(f"background-color: {COLORS['bg']}; border-radius: 8px;")
        preview_row.addWidget(self.preview_image)

        info_col = QVBoxLayout()
        info_col.setSpacing(10)
        info_col.setAlignment(Qt.AlignTop)

        self.filename_label = QLabel("")
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        info_col.addWidget(self.filename_label)

        self.info_grid = QGridLayout()
        self.info_grid.setHorizontalSpacing(14)
        self.info_grid.setVerticalSpacing(6)
        info_col.addLayout(self.info_grid)
        info_col.addStretch(1)

        preview_row.addLayout(info_col, stretch=1)
        outer.addWidget(preview_card)

        list_label = QLabel("이 그룹의 사진")
        list_label.setStyleSheet("font-weight: 700;")
        outer.addWidget(list_label)

        # --- 아래: 목록(세로 스크롤만 — 가로 스크롤은 절대 안 생기게 열 개수를
        # 창 너비에 맞춰 다시 계산한다) ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setMinimumHeight(200)
        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(CELL_SPACING)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self._grid_container)
        outer.addWidget(self.scroll_area, stretch=1)

    def set_group(self, label: str, files: list) -> None:
        self.title_label.setText(f"{label} · {len(files)}장")
        self._files = files

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cells = []

        for info in files:
            pixmap = load_thumbnail(info.path, THUMB_SIZE)
            cell = ClickableThumbnail(pixmap, info.filename, size=THUMB_SIZE, margin=CELL_MARGIN)
            cell.clicked.connect(lambda info=info: self._on_thumbnail_clicked(info))
            self._cells.append(cell)

        if files:
            self._on_thumbnail_clicked(files[0])

        self._last_columns = -1  # 새 그룹이니 강제로 다시 배치
        self._relayout_grid()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_grid()

    def _relayout_grid(self):
        if not self._cells:
            return

        cell_width = THUMB_SIZE + CELL_MARGIN * 2 + CELL_SPACING
        available = self.scroll_area.viewport().width() or self.width()
        columns = max(1, available // cell_width)
        if columns == self._last_columns:
            return
        self._last_columns = columns

        for cell in self._cells:
            self._grid.removeWidget(cell)
        for idx, cell in enumerate(self._cells):
            self._grid.addWidget(cell, idx // columns, idx % columns)

    def _on_thumbnail_clicked(self, info) -> None:
        pixmap = load_thumbnail(info.path, PREVIEW_SIZE)
        if pixmap is not None:
            self.preview_image.setPixmap(pixmap)
            self.preview_image.setText("")
        else:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("미리보기를 생성할 수 없습니다.")

        self.filename_label.setText(info.filename)
        self._set_info_rows(info)

        for cell, file_info in zip(self._cells, self._files):
            cell.set_active(file_info is info)

    def _set_info_rows(self, info) -> None:
        while self.info_grid.count():
            item = self.info_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = []
        if info.width and info.height:
            rows.append(("해상도", f"{info.width} × {info.height}"))
        rows.append(("파일 크기", format_file_size(info.file_size)))
        if info.captured_at:
            rows.append(("촬영일", info.captured_at.strftime("%Y-%m-%d")))

        for row, (label, value) in enumerate(rows):
            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
            value_widget = QLabel(value)
            self.info_grid.addWidget(label_widget, row, 0)
            self.info_grid.addWidget(value_widget, row, 1)
