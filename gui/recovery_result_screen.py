"""
gui/recovery_result_screen.py

PRD 21장 "Screen 06 — Recovery Result" 구현.
"""

from __future__ import annotations

import os
import sys
import subprocess

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
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

from gui.icons import status_icon_pixmap
from gui.result_screen import SummaryChip
from gui.theme import COLORS


def _list_icon_pixmap(kind: str, accent: str, size: int = 32) -> QPixmap:
    """목록 팝업 헤더 아이콘 — gui/icons.py의 공용 아이콘을 감싼 것. kind는
    DESIGN.md 아이콘 시스템의 성공/건너뜀/오류(success/skip/error) 그대로."""
    return status_icon_pixmap(kind, accent, size)


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

        self.title_label = QLabel("복구 완료")
        self.title_label.setObjectName("Title")
        card_layout.addWidget(self.title_label)

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

        self.open_folder_btn = QPushButton("폴더 열기")
        self.open_folder_btn.clicked.connect(self._open_folder)
        card_layout.addWidget(self.open_folder_btn)

        done_btn = QPushButton("결과 목록으로 돌아가기")
        done_btn.setObjectName("Primary")
        done_btn.clicked.connect(self.done_requested.emit)
        card_layout.addWidget(done_btn)

        outer.addWidget(card)

    def set_outcomes(self, outcomes: list, output_dir: str, title: str = "복구 완료"):
        self.outcomes = outcomes
        self.output_dir = output_dir
        self.title_label.setText(f"{title} 완료" if not title.endswith("완료") else title)

        success = sum(1 for o in outcomes if o.success and o.verified)
        partial = sum(1 for o in outcomes if o.success and not o.verified)
        skipped = sum(1 for o in outcomes if o.skipped)
        fail = sum(1 for o in outcomes if not o.success and not o.skipped)

        self.success_chip.set_value(success)
        self.partial_chip.set_value(partial)
        self.skipped_chip.set_value(skipped)
        self.fail_chip.set_value(fail)
        # output_dir이 빈 문자열인 건 "원본 삭제(대체)" 옵션을 쓴 경우뿐이다
        # (gui/recovery_screen.py::_start_recovery) — 파일마다 원래 있던
        # 폴더로 갔으므로 하나의 "저장 위치"로 보여줄 게 없다.
        if output_dir:
            self.output_label.setText(f"저장 위치:\n{output_dir}")
        else:
            self.output_label.setText("저장 위치: 사진마다 원래 있던 폴더(원본은 그 폴더의 임시휴지통으로 이동)")
        self.open_folder_btn.setVisible(bool(output_dir))

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
