"""
gui/recovery_result_screen.py

PRD 21장 "Screen 06 — Recovery Result" 구현.
"""

from __future__ import annotations

import os
import sys
import subprocess

from PySide6.QtCore import Qt, Signal, QUrl, QPointF
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QDialog,
    QListWidget,
    QListWidgetItem,
)

from gui.result_screen import SummaryChip
from gui.theme import COLORS


def _list_icon_pixmap(kind: str, accent: str, size: int = 32) -> QPixmap:
    """목록 팝업 헤더 아이콘 — 최근 검사 목록/확인 팝업과 같은 스타일(색 원 + 흰색
    벡터 글리프, 이모지 미사용). DESIGN.md 아이콘 시스템의 성공/건너뜀/오류 세 종류."""
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    def pt(x, y):
        return QPointF(offset + x * inner_scale, offset + y * inner_scale)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(0, 0, size, size)

    if kind == "success":
        pen = QPen(QColor("white"))
        pen.setWidthF(3 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(pt(5, 12.5))
        path.lineTo(pt(9.5, 17))
        path.lineTo(pt(19, 7))
        painter.drawPath(path)
    elif kind == "error":
        pen = QPen(QColor("white"))
        pen.setWidthF(3 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(pt(6.5, 6.5), pt(17.5, 17.5))
        painter.drawLine(pt(17.5, 6.5), pt(6.5, 17.5))
    elif kind == "skip":
        pen = QPen(QColor("white"))
        pen.setWidthF(3 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(pt(6, 12), pt(18, 12))

    painter.end()
    return pixmap


class RecoveryResultScreen(QWidget):
    done_requested = Signal()  # 결과 화면(Screen 03)으로 돌아가기

    def __init__(self, parent=None):
        super().__init__(parent)
        self.outcomes = []
        self.output_dir = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(440)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(14)

        title = QLabel("복구 완료")
        title.setObjectName("Title")
        card_layout.addWidget(title)

        # 상태별 개수 카드 = 동시에 버튼. SummaryChip을 clickable=True로 재사용해서
        # 누르면 해당 상태의 파일 목록을 보여준다(DESIGN.md "상태 요약 카드" 참고) —
        # 따로 "OO 보기" 버튼 행을 두지 않는다.
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        chips_row.addStretch(1)
        self.success_chip = SummaryChip("성공", COLORS["success"], clickable=True)
        self.partial_chip = SummaryChip("부분 성공", COLORS["warning"], clickable=True)
        self.skipped_chip = SummaryChip("건너뜀", COLORS["muted"], clickable=True)
        self.fail_chip = SummaryChip("실패", COLORS["danger"], clickable=True)
        self.success_chip.clicked.connect(
            lambda: self._show_list("성공/부분 성공 파일", self._success_lines(), "success", COLORS["success"])
        )
        self.partial_chip.clicked.connect(
            lambda: self._show_list("성공/부분 성공 파일", self._success_lines(), "success", COLORS["success"])
        )
        self.skipped_chip.clicked.connect(
            lambda: self._show_list("건너뛴 파일", self._skipped_lines(), "skip", COLORS["muted"])
        )
        self.fail_chip.clicked.connect(
            lambda: self._show_list("실패 파일", self._fail_lines(), "error", COLORS["danger"])
        )
        for chip in (self.success_chip, self.partial_chip, self.skipped_chip, self.fail_chip):
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        card_layout.addLayout(chips_row)

        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet(f"color: {COLORS['text_secondary']}; margin-top: 8px;")
        card_layout.addWidget(self.output_label)

        open_folder_btn = QPushButton("폴더 열기")
        open_folder_btn.clicked.connect(self._open_folder)
        card_layout.addWidget(open_folder_btn)

        done_btn = QPushButton("결과 목록으로 돌아가기")
        done_btn.setObjectName("Primary")
        done_btn.clicked.connect(self.done_requested.emit)
        card_layout.addWidget(done_btn)

        outer.addWidget(card)

    def set_outcomes(self, outcomes: list, output_dir: str):
        self.outcomes = outcomes
        self.output_dir = output_dir

        success = sum(1 for o in outcomes if o.success and o.verified)
        partial = sum(1 for o in outcomes if o.success and not o.verified)
        skipped = sum(1 for o in outcomes if o.skipped)
        fail = sum(1 for o in outcomes if not o.success and not o.skipped)

        self.success_chip.set_value(success)
        self.partial_chip.set_value(partial)
        self.skipped_chip.set_value(skipped)
        self.fail_chip.set_value(fail)
        self.output_label.setText(f"저장 위치:\n{output_dir}")

    def _success_lines(self) -> list[str]:
        return [
            f"{o.original.filename} → {o.output_path}"
            for o in self.outcomes
            if o.success
        ]

    def _skipped_lines(self) -> list[str]:
        return [
            f"{o.original.filename}: {o.error_message or '건너뜀'}"
            for o in self.outcomes
            if o.skipped
        ]

    def _fail_lines(self) -> list[str]:
        return [
            f"{o.original.filename}: {o.error_message or '알 수 없는 오류'}"
            for o in self.outcomes
            if not o.success and not o.skipped
        ]

    def _show_list(self, title: str, lines: list[str], icon_kind: str, accent: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        # 이 세션 창만 막고 다른 검사 세션 창은 계속 조작 가능하게 (다중 검사 지원)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(_list_icon_pixmap(icon_kind, accent))
        header_row.addWidget(icon_label)
        header_label = QLabel(f"{title} · {len(lines)}개" if lines else title)
        header_label.setStyleSheet(f"font-weight: 700; font-size: 15px; color: {accent};")
        header_row.addWidget(header_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        list_widget = QListWidget()
        if lines:
            for line in lines:
                list_widget.addItem(QListWidgetItem(line))
        else:
            placeholder = QListWidgetItem("해당하는 파일이 없습니다.")
            placeholder.setFlags(Qt.NoItemFlags)
            list_widget.addItem(placeholder)
        layout.addWidget(list_widget)

        close_btn = QPushButton("닫기")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def _open_folder(self):
        if not self.output_dir:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))
