"""
gui/date_group_detail_screen.py

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
from gui.thumbnail import ClickableThumbnail, ThumbnailLoadWorker, load_thumbnail
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
        # 그룹 안 사진이 많으면(수백 장) 그리드 셀마다 동기 디코딩을 다 돌리면
        # 화면 전환이 멈춘 것처럼 보인다(gui/trash_screen.py에서 같은 문제를
        # 겪고 고친 것과 동일) — 셀은 자리부터 만들어두고 썸네일은 백그라운드
        # 로딩으로 채운다. _thumb_cache는 그룹을 다시 열어도(뒤로 갔다가 다시
        # 클릭) 재사용된다.
        self._thumb_cache: dict[str, object] = {}  # path -> QImage | None
        self._pending_cells: dict[str, list[ClickableThumbnail]] = {}
        self._worker: ThumbnailLoadWorker | None = None

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

        if self._worker is not None:
            # 이전 그룹 로딩이 아직 안 끝났으면 취소만 하고 손을 뗀다 —
            # gui/trash_screen.py::refresh()와 같은 이유(QThread를 실행 중에
            # 강제로 없애면 크래시).
            self._worker.cancel()
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker = None

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cells = []
        self._pending_cells = {}

        for info in files:
            path_str = info.path
            cached = self._thumb_cache.get(path_str) if path_str in self._thumb_cache else None
            pixmap = QPixmap.fromImage(cached) if cached is not None else None
            cell = ClickableThumbnail(pixmap, info.filename, size=THUMB_SIZE, margin=CELL_MARGIN)
            cell.clicked.connect(lambda info=info: self._on_thumbnail_clicked(info))
            self._cells.append(cell)
            if path_str not in self._thumb_cache:
                # _pending_cells는 여기서 채워지는 순서(=화면 그리드 순서)
                # 그대로라, 그 순서를 백그라운드 워커에도 그대로 넘긴다 —
                # 아무 순서로나 로딩하면 화면에 보이는 앞쪽 사진보다 뒤쪽이
                # 먼저 채워져서 "안 불러와지는 것처럼" 보이는 문제가 있다.
                self._pending_cells.setdefault(path_str, []).append(cell)

        if files:
            self._on_thumbnail_clicked(files[0])

        self._last_columns = -1  # 새 그룹이니 강제로 다시 배치
        self._relayout_grid()

        missing = list(self._pending_cells.keys())
        if missing:
            self._worker = ThumbnailLoadWorker(missing, THUMB_SIZE, self)
            self._worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._worker.start()

    def stop_pending_work(self) -> None:
        """이 화면을 담은 창이 곧 닫히기 전에 불러서 백그라운드 썸네일 로딩을
        안전하게 멈춘다 — gui/trash_screen.py::stop_pending_work()와 같은 이유
        (QThread가 도는 중에 같이 없어지면 크래시 위험)."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait()
            self._worker = None

    def _on_thumbnail_ready(self, path_str: str, image) -> None:
        self._thumb_cache[path_str] = image
        cells = self._pending_cells.get(path_str)
        if not cells:
            return
        pixmap = QPixmap.fromImage(image) if image is not None else None
        for cell in cells:
            cell.set_pixmap(pixmap)

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
