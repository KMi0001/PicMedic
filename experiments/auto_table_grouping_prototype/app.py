"""
experiments/auto_table_grouping_prototype/app.py

gui/duplicate_screen.py의 "자동 추천" 표에서 "삭제될 파일"을 엑셀 행 그룹화
스타일로 펼쳐 보여주는 프로토타입 — 실제 위젯을 셀 안에 쌓는 방식(1차 시도,
사용자가 거부함) 대신, 진짜 테이블 행을 부모 행 바로 아래 숨겨뒀다가
[+]/[-] 토글로 보이기/숨기기만 하는 방식. 메인 앱은 아직 안 건드림 —
승인받으면 gui/duplicate_screen.py에 그대로 옮긴다.

실행: python experiments/auto_table_grouping_prototype/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QHeaderView,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# --- 가짜 데이터: (남길 파일, [삭제될 파일 목록], 전체 사유) ---
FAKE_ROWS = [
    (
        "photo.jpg  (C:/Users/JENN/Pictures/2024)",
        [
            ("photo_1.jpg  (C:/Users/JENN/Pictures/2024)", "파일명이 그룹 안 다른 파일의 복사본 패턴(번호 접미사)으로 보여요"),
        ],
        "파일명에 복사본 표시가 없는 유일한 파일",
    ),
    (
        "vacation.jpg  (C:/Users/JENN/Pictures/여행)",
        [
            ("vacation 복사본.jpg  (C:/Users/JENN/Downloads)", "파일명에 복사본 표시가 있어요 (복사본/사본/카카오톡 등)"),
            ("vacation(1).jpg  (C:/Users/JENN/카카오톡 받은 파일)", "파일명에 복사본 표시가 있어요 (복사본/사본/카카오톡 등)"),
        ],
        "파일명에 복사본 표시가 없는 유일한 파일",
    ),
    (
        "IMG_0021.jpg  (D:/백업/2023-11)",
        [
            ("IMG_0021.jpg  (D:/사진/2023-11)", "파일시스템 생성일: 2023-11-05 14:02 (남긴 파일보다 늦음)"),
        ],
        "파일시스템 생성일이 가장 이른 파일",
    ),
]


class GroupedAutoTable(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("자동 추천 표 — 행 그룹화 프로토타입")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setCentralWidget(central)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "남길 파일 (폴더)", "삭제될 파일", "사유"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 320)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(True)
        layout.addWidget(self.table)

        self._populate()
        self.resize(1000, 500)

    def _populate(self):
        table = self.table
        row = 0
        for keep_text, removed, reason in FAKE_ROWS:
            parent_row = row
            table.insertRow(parent_row)

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked)
            table.setItem(parent_row, 0, check_item)

            table.setItem(parent_row, 1, QTableWidgetItem(keep_text))

            toggle = QToolButton()
            toggle.setText(f"▸ {len(removed)}개")
            toggle.setCheckable(True)
            toggle.setAutoRaise(True)
            toggle.setCursor(Qt.PointingHandCursor)
            toggle.setStyleSheet("QToolButton { border: none; font-weight: 600; }")
            table.setCellWidget(parent_row, 2, toggle)

            table.setItem(parent_row, 3, QTableWidgetItem(reason))

            row += 1
            child_rows = []
            for file_text, file_reason in removed:
                table.insertRow(row)
                table.setRowHidden(row, True)

                blank = QTableWidgetItem("")
                blank.setFlags(Qt.NoItemFlags)
                table.setItem(row, 0, blank)

                keep_blank = QTableWidgetItem("")
                keep_blank.setFlags(Qt.NoItemFlags)
                table.setItem(row, 1, keep_blank)

                file_item = QTableWidgetItem(f"└ {file_text}")
                file_item.setForeground(Qt.darkGray)
                table.setItem(row, 2, file_item)

                reason_item = QTableWidgetItem(file_reason)
                reason_item.setForeground(Qt.darkGray)
                table.setItem(row, 3, reason_item)

                child_rows.append(row)
                row += 1

            def make_toggle_handler(btn=toggle, rows=child_rows, table=table):
                def handler(checked):
                    btn.setText(f"▾ {len(rows)}개" if checked else f"▸ {len(rows)}개")
                    for r in rows:
                        table.setRowHidden(r, not checked)
                return handler

            toggle.toggled.connect(make_toggle_handler())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = GroupedAutoTable()
    win.show()
    sys.exit(app.exec())
