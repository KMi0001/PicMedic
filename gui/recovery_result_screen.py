"""
gui/recovery_result_screen.py

PRD 21장 "Screen 06 — Recovery Result" 구현.
"""

from __future__ import annotations

import os
import sys
import subprocess

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
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

from gui.theme import COLORS


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

        self.success_label = QLabel()
        self.partial_label = QLabel()
        self.skipped_label = QLabel()
        self.fail_label = QLabel()
        for lbl, color in (
            (self.success_label, COLORS["success"]),
            (self.partial_label, COLORS["warning"]),
            (self.skipped_label, COLORS["text_secondary"]),
            (self.fail_label, COLORS["danger"]),
        ):
            lbl.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
            card_layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        self.view_success_btn = QPushButton("성공 파일 보기")
        self.view_success_btn.clicked.connect(lambda: self._show_list("성공/부분 성공 파일", self._success_lines()))
        self.view_skipped_btn = QPushButton("건너뜀 파일 보기")
        self.view_skipped_btn.clicked.connect(lambda: self._show_list("건너뛴 파일", self._skipped_lines()))
        self.view_fail_btn = QPushButton("실패 파일 보기")
        self.view_fail_btn.clicked.connect(lambda: self._show_list("실패 파일", self._fail_lines()))
        btn_row.addWidget(self.view_success_btn)
        btn_row.addWidget(self.view_skipped_btn)
        btn_row.addWidget(self.view_fail_btn)
        card_layout.addLayout(btn_row)

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

        self.success_label.setText(f"성공 {success}")
        self.partial_label.setText(f"부분 성공 {partial}")
        self.skipped_label.setText(f"건너뜀 {skipped}")
        self.fail_label.setText(f"실패 {fail}")
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

    def _show_list(self, title: str, lines: list[str]):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
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
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def _open_folder(self):
        if not self.output_dir:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))
