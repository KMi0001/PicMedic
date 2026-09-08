"""
experiments/similar_grouping_prototype/app.py

gui/similar_screen.py의 유사 사진 카드(썸네일을 나란히 보여주는 가로 배치)를
gui/duplicate_screen.py와 같은 "체크옵션 / 파일명(로컬주소) / 구분 / 사유" 표
형태로 바꾸는 프로토타입(2026-09-08, 사용자 요청 — "유사사진도 동일하게").
메인 앱은 아직 안 건드림.

주의할 점(중복 사진 화면과 다른 부분): 유사 사진은 바이트 단위로 똑같지
않은 "추정" 매칭이라 실제 썸네일을 봐야 오탐인지 판단할 수 있다 — 표 안
"파일명(로컬주소)" 칸에 작은 썸네일 아이콘을 같이 넣어서 표 형태를 유지하면서도
사진을 볼 수 있게 했다. 다만 지금(카드, 가로 나열)처럼 사진 두 장을 나란히
크게 비교하는 것보다는 한 장씩 세로로 쌓여 보이므로 비교가 상대적으로
불편할 수 있다 — 이 트레이드오프를 사용자에게 그대로 보여주고 확인받는다.

그 외 개선: 라디오를 바꿀 때마다 "구분"(유지/삭제)이 실시간으로 바뀐다
(중복 화면의 "폴더 단위" 표는 후보마다 역할이 이미 고정이라 정적으로
"유지"만 표시했지만, 유사 사진은 어떤 사진이 유지될지 라디오로 그때그때
정해지므로 살아있게 갱신하는 게 더 맞다).

실행: python experiments/similar_grouping_prototype/app.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

THUMB = 48

# 가짜 유사 그룹: (그룹 설명, 유사도 근거, [(파일명, 로컬주소, 색상)])
FAKE_GROUPS = [
    {
        "note": "이미지 유사도 거리 2 (0에 가까울수록 거의 같은 사진)",
        "photos": [
            ("trip1.jpg", "D:/Photos/2024_여행", (230, 126, 34)),
            ("trip1_edit.jpg", "C:/Users/JENN/Downloads", (231, 140, 60)),
        ],
    },
]


def _fake_pixmap(color, size=THUMB) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(*color))
    return pix


class SimilarGroupingTable(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("유사 사진 — 표 형태 프로토타입")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setCentralWidget(central)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "파일명 (로컬주소)", "구분", "사유"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 260)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.table)

        self._populate()
        self.resize(1000, 400)

    def _populate(self):
        table = self.table
        row = 0
        for group in FAKE_GROUPS:
            button_group = QButtonGroup(table)

            # 건너뛰기
            table.insertRow(row)
            skip_radio = QRadioButton()
            skip_radio.setChecked(True)
            skip_radio.setToolTip(group["note"])
            button_group.addButton(skip_radio)
            table.setCellWidget(row, 0, skip_radio)
            skip_item = QTableWidgetItem("이 그룹은 정리하지 않음(건너뛰기)")
            table.setItem(row, 1, skip_item)
            for c, text in ((2, "-"), (3, group["note"])):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.NoItemFlags)
                table.setItem(row, c, it)
            row += 1

            status_items = []
            radios = []
            for filename, folder, color in group["photos"]:
                table.insertRow(row)

                radio = QRadioButton()
                button_group.addButton(radio)
                radios.append(radio)
                table.setCellWidget(row, 0, radio)

                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(4, 2, 4, 2)
                cell_layout.setSpacing(8)
                thumb_label = QLabel()
                thumb_label.setPixmap(_fake_pixmap(color))
                thumb_label.setFixedSize(THUMB, THUMB)
                cell_layout.addWidget(thumb_label)
                text_label = QLabel(f"{filename}  ({folder})")
                cell_layout.addWidget(text_label, stretch=1)
                table.setCellWidget(row, 1, cell)
                table.setRowHeight(row, THUMB + 8)

                status_item = QTableWidgetItem("삭제")
                table.setItem(row, 2, status_item)
                status_items.append(status_item)

                table.setItem(row, 3, QTableWidgetItem(""))

                row += 1

            def make_handler(idx, items=status_items, radios=radios):
                def handler(checked):
                    if checked:
                        for i, it in enumerate(items):
                            it.setText("유지" if i == idx else "삭제")
                return handler

            for i, radio in enumerate(radios):
                radio.toggled.connect(make_handler(i))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SimilarGroupingTable()
    win.show()
    sys.exit(app.exec())
