"""
gui/duplicate_screen.py

Phase 2 "사진 정리" 1차 범위 — 정확 중복(파일 내용 SHA-256) 탐지 결과를 보여주는
화면. PHASE2_사진정리_기획.md 참고. 다시 스캔하지 않고, 같은 검사 세션에서 이미
계산된 FileInfo.content_hash로 ScanResult.duplicate_groups()를 호출해 그룹만
보여준다 — 삭제/이동 등 실제 정리 액션은 1차 범위 밖(찾아서 보여주기까지만).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
)

from gui.result_screen import SummaryChip
from gui.theme import COLORS
from utils.file_utils import format_file_size


def _duplicate_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 겹친 사각형 두 개로 "복사본이 있다"는 의미.
    검사 결과 화면의 돋보기 아이콘과 같은 아웃라인 스트로크 스타일."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def r(x, y, w, h):
        from PySide6.QtCore import QRectF

        return QRectF(x * scale, y * scale, w * scale, h * scale)

    painter.drawRoundedRect(r(3, 6, 13, 13), 2 * scale, 2 * scale)
    painter.drawRoundedRect(r(8, 1, 13, 13), 2 * scale, 2 * scale)

    painter.end()
    return pixmap


class DuplicateScreen(QWidget):
    """검사 결과 화면(gui/result_screen.py)의 "중복 파일 보기" 버튼으로 들어오는
    화면. 같은 스캔 세션(gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[list] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_duplicate_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("중복 사진")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.group_chip = SummaryChip("중복 그룹", COLORS["warning"])
        self.file_chip = SummaryChip("중복 파일", COLORS["warning"])
        chips_row.addWidget(self.group_chip)
        chips_row.addWidget(self.file_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        self.empty_label = QLabel("중복된 파일이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll_area.setWidget(self._list_container)
        outer.addWidget(self.scroll_area, stretch=1)

    def set_result(self, result) -> None:
        """검사 결과가 바뀔 때(재검사 등) 호출 — result.duplicate_groups()로
        중복 그룹을 다시 계산해서 보여준다."""
        self._groups = result.duplicate_groups() if result else []

        total_files = sum(len(g) for g in self._groups)
        self.group_chip.set_value(len(self._groups))
        self.file_chip.set_value(total_files)

        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.empty_label.setVisible(not self._groups)
        self.scroll_area.setVisible(bool(self._groups))

        for idx, group in enumerate(self._groups, start=1):
            self._list_layout.insertWidget(idx - 1, self._build_group_card(idx, group))

    def _build_group_card(self, idx: int, group: list) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        header = QLabel(f"그룹 {idx} · {len(group)}개 파일 · 각 {format_file_size(group[0].file_size)}")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        for info in group:
            row = QLabel(info.path)
            row.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            row.setWordWrap(True)
            layout.addWidget(row)

        return card
