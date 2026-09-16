"""
experiments/organize_hub_redesign_mockup/merged_screen_options.py

"검사 결과 화면 + 정리 허브를 하나로 합치면 어떤 모습일까" 논의용 목업 2종.
진짜 데이터/기능은 없고 더미 값만 채워서 레이아웃만 비교한다.

옵션 A: 지금 검사 결과 표(체크박스+확장자 변환)를 그대로 두고 그 아래에
        정리 카드를 붙인다 — 진단 기능이 하나도 안 줄어든다.
옵션 B: 정리(표+카드)를 화면 중심에 두고, 체크박스·확장자 변환 같은 진단
        전용 UI는 걷어낸다(그런 액션은 사진 상세화면에서만).

실행:
    python experiments/organize_hub_redesign_mockup/merged_screen_options.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.result_screen import SummaryChip, _format_mtime, _NumericSortItem, _qcolor, _safe_mtime
from gui.theme import COLORS, STATUS_COLORS, STATUS_DOT, get_stylesheet
from utils.file_utils import format_file_size

# (상태, 파일명, 확장자, 크기(bytes), 수정일, 카테고리)
ROWS = [
    ("정상", "IMG_2653", "PNG", 1_150_000, "2024-06-22", "스크린샷/문서"),
    ("정상", "KakaoTalk_2026", "JPG", 3_400_000, "2026-08-14", "음식 사진"),
    ("정상", "photo_0091", "HEIC", 2_800_000, "2026-07-02", "동물친구들"),
    ("형식 불일치", "IMG_2938", "PNG", 2_200_000, "2026-05-30", "스크린샷/문서"),
    ("정상", "DSC_0442", "JPG", 5_100_000, "2026-01-11", "풍경 사진"),
    ("정상", "야경_강남", "JPG", 4_400_000, "2025-12-24", "야경 사진"),
    ("부분 손상", "고양이_낮잠", "JPG", 3_900_000, "2026-03-03", "동물친구들"),
    ("정상", "스캔_영수증", "PNG", 600_000, "2026-02-19", "스크린샷/문서"),
]

CATEGORY_BADGE_COLOR = {
    "동물친구들": "#8FA06B",
    "음식 사진": "#D4934F",
    "스크린샷/문서": "#7A7060",
    "야경 사진": "#5C6BC0",
    "풍경 사진": "#4E9A8F",
}

CARD_DEFS = [
    ("중복 파일", "없음"),
    ("유사 사진", "3쌍"),
    ("날짜별", "4개 묶음"),
    ("도시별", "2개 도시"),
    ("동물친구들", "2장"),
    ("음식 사진", "1장"),
    ("스크린샷/문서", "3장"),
    ("야경 사진", "1장"),
    ("풍경 사진", "1장"),
]


def build_category_badge(text: str) -> QLabel:
    color = CATEGORY_BADGE_COLOR.get(text, COLORS["muted"])
    label = QLabel(text)
    label.setStyleSheet(f"color: white; background-color: {color}; border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 600;")
    label.setAlignment(Qt.AlignCenter)
    return label


def build_table(with_checkbox: bool) -> QTableWidget:
    columns = ["상태", "파일명", "확장자", "크기", "수정일", "카테고리"]
    offset = 0
    if with_checkbox:
        columns = [""] + columns
        offset = 1
    table = QTableWidget(len(ROWS), len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(1 + offset, QHeaderView.Stretch)
    for col in range(len(columns)):
        if col != 1 + offset:
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    for row, (status, filename, ext, size_bytes, mtime, category) in enumerate(ROWS):
        col = offset
        if with_checkbox:
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            table.setItem(row, 0, check_item)

        status_item = QTableWidgetItem(f"{STATUS_DOT.get(status, '')} {status}")
        status_item.setForeground(_qcolor(STATUS_COLORS.get(status, COLORS['text'])))
        table.setItem(row, col, status_item)
        table.setItem(row, col + 1, QTableWidgetItem(filename))
        table.setItem(row, col + 2, QTableWidgetItem(ext))

        size_item = _NumericSortItem(format_file_size(size_bytes))
        size_item.setData(Qt.UserRole, size_bytes)
        table.setItem(row, col + 3, size_item)

        date_item = _NumericSortItem(mtime)
        date_item.setData(Qt.UserRole, mtime)
        table.setItem(row, col + 4, date_item)

        table.setItem(row, col + 5, QTableWidgetItem(category))
        table.setCellWidget(row, col + 5, build_category_badge(category))

    table.setSortingEnabled(True)
    return table


def build_cards_row(compact: bool) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    for title, count in CARD_DEFS:
        card = QFrame()
        card.setObjectName("Card")
        card.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(card)
        pad = 10 if compact else 16
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: 700; font-size: {'12px' if compact else '13px'};")
        layout.addWidget(title_label)
        count_label = QLabel(count)
        count_label.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 700; font-size: {'14px' if compact else '18px'};")
        layout.addWidget(count_label)
        row.addWidget(card)
    return row


def build_option_a() -> QWidget:
    """옵션 A: 지금 검사 결과 표(체크박스+확장자 변환) 그대로 + 아래에 정리 카드."""
    window = QWidget()
    window.setWindowTitle("옵션 A")
    window.setStyleSheet(f"background-color: {COLORS['bg']};")
    outer = QVBoxLayout(window)
    outer.setContentsMargins(40, 28, 40, 28)
    outer.setSpacing(12)

    title = QLabel("검사 결과")
    title.setObjectName("Title")
    outer.addWidget(title)

    chips_row = QHBoxLayout()
    chips_row.setSpacing(8)
    for label, color, value in [
        ("전체", COLORS["text"], 8), ("정상", STATUS_COLORS["정상"], 6),
        ("형식 불일치", STATUS_COLORS["형식_불일치"], 1), ("부분 손상", STATUS_COLORS["부분_손상"], 1),
    ]:
        chip = SummaryChip(label, color)
        chip.set_value(value)
        chips_row.addWidget(chip)
    chips_row.addStretch(1)
    outer.addLayout(chips_row)

    search_row = QHBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText("파일명·확장자 검색")
    search_row.addWidget(search, stretch=1)
    outer.addLayout(search_row)

    table = build_table(with_checkbox=True)
    outer.addWidget(table, stretch=1)

    action_row = QHBoxLayout()
    action_row.addStretch(1)
    convert_btn = QPushButton("선택 항목 확장자 변환")
    convert_btn.setObjectName("Primary")
    action_row.addWidget(convert_btn)
    outer.addLayout(action_row)

    organize_label = QLabel("정리")
    organize_label.setStyleSheet("font-weight: 700; font-size: 14px; margin-top: 8px;")
    outer.addWidget(organize_label)
    outer.addLayout(build_cards_row(compact=False))

    window.resize(1180, 900)
    return window


def build_option_b() -> QWidget:
    """옵션 B: 정리(표+카드) 중심, 체크박스·확장자 변환은 걷어냄."""
    window = QWidget()
    window.setWindowTitle("옵션 B")
    window.setStyleSheet(f"background-color: {COLORS['bg']};")
    outer = QVBoxLayout(window)
    outer.setContentsMargins(40, 28, 40, 28)
    outer.setSpacing(12)

    title_row = QHBoxLayout()
    title = QLabel("정리")
    title.setObjectName("Title")
    title_row.addWidget(title)
    title_row.addStretch(1)
    hint = QLabel("전체 8장 · 형식 불일치 1 · 부분 손상 1")
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    title_row.addWidget(hint)
    outer.addLayout(title_row)

    outer.addLayout(build_cards_row(compact=True))

    table_label = QLabel("전체 사진 목록")
    table_label.setStyleSheet("font-weight: 700; font-size: 14px; margin-top: 8px;")
    outer.addWidget(table_label)

    table = build_table(with_checkbox=False)
    outer.addWidget(table, stretch=1)

    note = QLabel("확장자 변환 등 파일 수정 액션은 사진을 열었을 때(상세화면)에서만 할 수 있어요.")
    note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    outer.addWidget(note)

    window.resize(1180, 780)
    return window


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    win_a = build_option_a()
    win_a.show()
    app.processEvents()
    win_a.grab().save(str(Path(__file__).resolve().parent / "option_a.png"))

    win_b = build_option_b()
    win_b.show()
    app.processEvents()
    win_b.grab().save(str(Path(__file__).resolve().parent / "option_b.png"))

    print("저장 완료: option_a.png, option_b.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
