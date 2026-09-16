"""
experiments/organize_hub_redesign_mockup/mockup.py

"정리 허브 카드 + 통합 사진 목록(상태/파일명/확장자/크기/수정일/카테고리, 전부
정렬 가능)" 새 레이아웃이 실제로 어떻게 보일지 확인하기 위한 일회성 목업.
진짜 데이터/기능은 없고 더미 값만 채워서 화면 배치만 검증한다 — 기획 논의용
스크린샷 한 장이 목적.

실행:
    QT_QPA_PLATFORM=offscreen python experiments/organize_hub_redesign_mockup/mockup.py
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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS, get_stylesheet
from utils.file_utils import format_file_size


class _NumericSortItem(QTableWidgetItem):
    """gui/result_screen.py의 같은 클래스와 동일한 패턴 — 표시 텍스트가 아니라
    Qt.UserRole에 저장한 실제 값(바이트 수, 타임스탬프) 기준으로 정렬한다."""

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            self_key = self.data(Qt.UserRole)
            other_key = other.data(Qt.UserRole)
            if self_key is not None and other_key is not None:
                return self_key < other_key
        return super().__lt__(other)

CARD_DEFS = [
    ("동물친구들", "42장", "AI로 동물이 나온 사진을 찾아 모아요."),
    ("음식 사진", "18장", "AI로 음식이 나온 사진을 찾아 모아요."),
    ("스크린샷/문서", "31장", "AI로 스크린샷·문서 사진을 찾아 모아요."),
    ("야경 사진", "6장", "AI로 밤에 찍은 야경 사진을 찾아 모아요."),
    ("풍경 사진", "24장", "AI로 풍경 사진을 찾아 모아요."),
]

# (상태, 파일명, 확장자, 크기(bytes), 수정일(YYYY-MM-DD), 카테고리) —
# gui/result_screen.py 검사 결과 표와 같은 컬럼 구성.
ROW_DEFS = [
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


def build_card(title: str, count: str, desc: str) -> QFrame:
    card = QFrame()
    card.setObjectName("Card")
    card.setFixedWidth(190)
    card.setCursor(Qt.PointingHandCursor)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(6)

    title_row = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: 700; font-size: 13px;")
    title_row.addWidget(title_label)
    title_row.addStretch(1)
    layout.addLayout(title_row)

    count_label = QLabel(count)
    count_label.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 700; font-size: 20px;")
    layout.addWidget(count_label)

    desc_label = QLabel(desc)
    desc_label.setWordWrap(True)
    desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    layout.addWidget(desc_label)

    folder_btn = QPushButton("폴더 만들기")
    folder_btn.setStyleSheet(
        f"QPushButton {{ padding: 5px 8px; font-size: 11px; border-radius: 6px; "
        f"border: 1px solid {COLORS['border']}; background: {COLORS['surface']}; }} "
        f"QPushButton:hover {{ border-color: {COLORS['primary']}; }}"
    )
    layout.addWidget(folder_btn)

    return card


def build_category_badge(text: str) -> QLabel:
    color = CATEGORY_BADGE_COLOR.get(text, COLORS["muted"])
    label = QLabel(text)
    label.setStyleSheet(
        f"color: white; background-color: {color}; border-radius: 8px; "
        f"padding: 2px 8px; font-size: 11px; font-weight: 600;"
    )
    label.setAlignment(Qt.AlignCenter)
    return label


STATUS_COLOR = {
    "정상": COLORS["success"],
    "형식 불일치": COLORS["warning"],
    "부분 손상": COLORS["danger"],
}


def build_status_label(text: str) -> QLabel:
    color = STATUS_COLOR.get(text, COLORS["muted"])
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-weight: 600; font-size: 12px;")
    return label


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(get_stylesheet())

    window = QWidget()
    window.setWindowTitle("정리 허브 목업")
    window.setStyleSheet(f"background-color: {COLORS['bg']};")
    outer = QVBoxLayout(window)
    outer.setContentsMargins(48, 32, 48, 32)
    outer.setSpacing(16)

    title_row = QHBoxLayout()
    title = QLabel("정리")
    title.setObjectName("Title")
    title_row.addWidget(title)
    title_row.addStretch(1)
    back_btn = QPushButton("← 뒤로")
    title_row.addWidget(back_btn)
    outer.addLayout(title_row)

    hint = QLabel("카테고리는 백그라운드에서 자동으로 채워져요. 카드를 누르면 그 카테고리를 폴더로 정리할 수 있어요.")
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    outer.addWidget(hint)

    cards_row = QHBoxLayout()
    cards_row.setSpacing(12)
    for card_title, count, desc in CARD_DEFS:
        cards_row.addWidget(build_card(card_title, count, desc))
    cards_row.addStretch(1)
    outer.addLayout(cards_row)

    list_label = QLabel("전체 사진 목록 (모든 컬럼 클릭 시 정렬 — gui/result_screen.py 검사 결과 표와 동일)")
    list_label.setStyleSheet("font-weight: 700; font-size: 14px; margin-top: 8px;")
    outer.addWidget(list_label)

    columns = ["상태", "파일명", "확장자", "크기", "수정일", "카테고리"]
    table = QTableWidget(len(ROW_DEFS), len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    for col in (0, 2, 3, 4, 5):
        table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    for row, (status, filename, ext, size_bytes, mtime, category) in enumerate(ROW_DEFS):
        table.setItem(row, 0, QTableWidgetItem(status))
        table.setCellWidget(row, 0, build_status_label(status))
        table.setItem(row, 1, QTableWidgetItem(filename))
        table.setItem(row, 2, QTableWidgetItem(ext))

        size_item = _NumericSortItem(format_file_size(size_bytes))
        size_item.setData(Qt.UserRole, size_bytes)
        table.setItem(row, 3, size_item)

        date_item = _NumericSortItem(mtime)
        date_item.setData(Qt.UserRole, mtime)
        table.setItem(row, 4, date_item)

        # 정렬은 실제 텍스트 기준으로 되도록 아이템을 먼저 심고, 그 위에 배지
        # 위젯을 얹는다(표시는 배지, 정렬 기준은 텍스트) — 상태 컬럼도 동일.
        table.setItem(row, 5, QTableWidgetItem(category))
        table.setCellWidget(row, 5, build_category_badge(category))

    # 셀 위젯(배지)을 다 심은 "뒤에" 정렬을 켠다 — 먼저 켜두면 setItem 때마다
    # 즉시 재정렬되면서 setCellWidget이 심어둔 위젯은 원래 행 위치에 남아
    # 텍스트와 배지가 서로 다른 행으로 어긋나는 Qt의 알려진 함정이 있다.
    table.setSortingEnabled(True)
    table.setMinimumHeight(260)
    outer.addWidget(table, stretch=1)

    window.resize(1120, 720)
    window.show()

    out_path = Path(__file__).resolve().parent / "mockup.png"
    pixmap = window.grab()
    pixmap.save(str(out_path))
    print(f"저장: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
