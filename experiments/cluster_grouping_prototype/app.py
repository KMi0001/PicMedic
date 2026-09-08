"""
experiments/cluster_grouping_prototype/app.py

gui/duplicate_screen.py의 "폴더 단위로 정리 가능" 카드를 표로 바꾸는
프로토타입 — 2차 시안(2026-09-08, 사용자 피드백으로 재설계):
"체크옵션 / ▼ 파일명(로컬주소) / 구분 / 사유" 4칸으로 통일하고, "남길
파일"/"삭제될 파일"을 별도 칸으로 나누는 대신 구분(유지/삭제) 값으로만
표시한다. 메인 앱은 아직 안 건드림.

바뀌는 점(1차 시안 대비):
- 칼럼이 "체크옵션 / ▼ 파일명(로컬주소) / 구분 / 사유"로 통일됨 — 남길
  파일이든 지워질 파일이든 같은 모양의 행으로 보이고, "구분" 칸이
  "유지"/"삭제"만 표시한다.
- ▼는 별도 버튼이 아니라 "파일명(로컬주소)" 칸 자체에 붙어서, 그 행(폴더
  후보)을 누르면 바로 아래에 그룹별 영향(하위 행, 구분="삭제")이 펼쳐진다.
- 조합 요약 회색 줄을 없애 더 깔끔하게(사용자 피드백 "깔끔할듯").

실행: python experiments/cluster_grouping_prototype/app.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QHeaderView,
    QMainWindow,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# 가짜 클러스터 데이터: (조합 설명, [(폴더 라벨, 이 폴더를 남기면 그룹별로 지워질 파일들, 추천여부)], 그룹 수)
FAKE_CLUSTERS = [
    {
        "summary": "폴더 2개 조합 · 2개 그룹에 적용",
        "options": [
            {
                "label": "2024 정리본  (D:/Photos/2024_정리본)",
                "removed_by_group": [
                    ("그룹 1", ["sunset_copy.jpg"]),
                    ("그룹 2", ["cat_1.jpg"]),
                ],
                "recommended": True,
                "reason": "파일시스템 생성일이 가장 이른 폴더",
            },
            {
                "label": "카카오톡 받은 파일  (C:/Users/JENN/Downloads/카카오톡 받은 파일)",
                "removed_by_group": [
                    ("그룹 1", ["sunset.jpg"]),
                    ("그룹 2", ["cat.jpg"]),
                ],
                "recommended": False,
                "reason": "",
            },
        ],
    },
]


class ClusterGroupingTable(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("폴더 단위 카드 — 행 그룹화 프로토타입")

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
        self.resize(1000, 500)

    def _populate(self):
        table = self.table
        row = 0
        for cluster in FAKE_CLUSTERS:
            button_group = QButtonGroup(table)

            # 건너뛰기 라디오 — 구분/사유는 의미가 없으니 "-"
            table.insertRow(row)
            skip_radio = QRadioButton()
            skip_radio.setChecked(True)
            skip_radio.setToolTip(cluster["summary"])  # 조합 요약은 툴팁으로만(회색 줄 없이 깔끔하게)
            button_group.addButton(skip_radio)
            table.setCellWidget(row, 0, skip_radio)
            skip_label = QTableWidgetItem("이 조합은 정리하지 않음")
            table.setItem(row, 1, skip_label)
            for c, text in ((2, "-"), (3, "-")):
                blank = QTableWidgetItem(text)
                blank.setFlags(Qt.NoItemFlags)
                table.setItem(row, c, blank)
            row += 1

            for option in cluster["options"]:
                table.insertRow(row)

                radio = QRadioButton()
                button_group.addButton(radio)
                if option["recommended"]:
                    radio.setChecked(True)
                    skip_radio.setChecked(False)
                table.setCellWidget(row, 0, radio)

                # ▼는 별도 칸이 아니라 "파일명(로컬주소)" 칸 자체에 붙어서,
                # 이 행(폴더 후보)을 누르면 그룹별 영향이 바로 아래 펼쳐진다.
                toggle_btn = QToolButton()
                toggle_btn.setText(f"▸ {option['label']}")
                toggle_btn.setCheckable(True)
                toggle_btn.setAutoRaise(True)
                toggle_btn.setCursor(Qt.PointingHandCursor)
                toggle_btn.setStyleSheet("QToolButton { border: none; text-align: left; }")
                table.setCellWidget(row, 1, toggle_btn)

                keep_status = QTableWidgetItem("유지")
                table.setItem(row, 2, keep_status)

                reason_item = QTableWidgetItem(f"추천 — {option['reason']}" if option["recommended"] else "")
                table.setItem(row, 3, reason_item)

                row += 1
                child_rows = []
                for group_label, removed_files in option["removed_by_group"]:
                    for filename in removed_files:
                        table.insertRow(row)
                        table.setRowHidden(row, True)

                        blank0 = QTableWidgetItem("")
                        blank0.setFlags(Qt.NoItemFlags)
                        table.setItem(row, 0, blank0)

                        file_item = QTableWidgetItem(f"└ {filename}")
                        table.setItem(row, 1, file_item)

                        del_status = QTableWidgetItem("삭제")
                        table.setItem(row, 2, del_status)

                        group_item = QTableWidgetItem(group_label)
                        table.setItem(row, 3, group_item)

                        for it in (file_item, del_status, group_item):
                            it.setForeground(Qt.darkGray)

                        child_rows.append(row)
                        row += 1

                def make_handler(btn=toggle_btn, rows=child_rows, label=option["label"], table=table):
                    def handler(checked):
                        btn.setText(f"▾ {label}" if checked else f"▸ {label}")
                        for r in rows:
                            table.setRowHidden(r, not checked)
                    return handler

                toggle_btn.toggled.connect(make_handler())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ClusterGroupingTable()
    win.show()
    sys.exit(app.exec())
