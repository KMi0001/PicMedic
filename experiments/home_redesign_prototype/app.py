"""
experiments/home_redesign_prototype/app.py

홈 화면 재구성(검사/진단/정리 3버튼 + 최근 검사 제거) 검증용 던지는(throwaway)
프로토타입 — 실제 gui/home_screen.py는 건드리지 않고, 세 가지 UX 개선안을
각각 PySide6로 그려서 스크린샷으로 비교한다(HTML 목업 대신 실제 위젯으로
그리는 팀 원칙, feedback_ui_workflow 메모리 참고).

python experiments/home_redesign_prototype/app.py 로 실행하면
_out/concept_a.png, _out/concept_b_before.png, _out/concept_b_after.png,
_out/concept_c.png 를 만든다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import APP_STYLESHEET, COLORS
from gui.home_screen import SelectionCard

OUT_DIR = Path(__file__).resolve().parent / "_out"
CONTENT_WIDTH = 520


def _outline_icon(color: str, size: int, draw) -> QPixmap:
    """gui/result_screen.py::_outline_icon과 같은 뼈대(아웃라인 스트로크 아이콘
    공통 팩토리) — 프로토타입이라 import 대신 그대로 복붙(다른 정리 화면
    아이콘들도 다 이렇게 파일마다 따로 둠, 재사용 abstraction 안 만드는 게
    이 코드베이스 관례)."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    draw(painter, scale)
    painter.end()
    return pixmap


def _scan_icon(color: str, size: int = 26) -> QPixmap:
    """검사 = 돋보기 (gui/result_screen.py::_search_icon_pixmap과 동일 모양)."""

    def draw(p, s):
        p.drawEllipse(QPointF(10.5 * s, 10.5 * s), 6.5 * s, 6.5 * s)
        p.drawLine(QPointF(15.2 * s, 15.2 * s), QPointF(20 * s, 20 * s))

    return _outline_icon(color, size, draw)


def _diagnose_icon(color: str, size: int = 26) -> QPixmap:
    """진단 = 맥박(EKG) 선 — 화질/손상 정도를 "측정"한다는 인상."""

    def draw(p, s):
        pts = [
            (2, 13), (6, 13), (8, 7), (11, 19), (14, 5), (16, 13), (22, 13),
        ]
        p.drawPolyline([QPointF(x * s, y * s) for x, y in pts])

    return _outline_icon(color, size, draw)


def _organize_icon(color: str, size: int = 26) -> QPixmap:
    """정리 = 폴더 안에 가지런한 줄 — "가지런히 정리됨"의 인상."""

    def draw(p, s):
        p.drawRoundedRect(QRectF(2 * s, 6 * s, 20 * s, 14 * s), 2 * s, 2 * s)
        p.drawLine(QPointF(2 * s, 6 * s), QPointF(8 * s, 6 * s))
        for y in (11, 14.5, 18):
            p.drawLine(QPointF(6 * s, y * s), QPointF(18 * s, y * s))

    return _outline_icon(color, size, draw)


class ActionCard(QFrame):
    """검사/진단/정리 액션 카드 하나 — 아이콘 + 제목 + 짧은 설명."""

    clicked = Signal()

    def __init__(self, icon_pixmap: QPixmap, title: str, desc: str, emphasize: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        border = f"2px solid {COLORS['primary']}" if emphasize else f"1px solid {COLORS['border']}"
        self.setStyleSheet(
            f"QFrame#Card {{ border: {border}; border-radius: 14px; background-color: {COLORS['surface']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignHCenter)

        icon_label = QLabel()
        icon_label.setFixedSize(48, 48)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"background-color: {COLORS['selection']}; border-radius: 24px;")
        icon_label.setPixmap(icon_pixmap)
        layout.addWidget(icon_label, alignment=Qt.AlignHCenter)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 14.5px; font-weight: 700; background: transparent;")
        layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px; background: transparent;")
        layout.addWidget(desc_label)


class DropActionCard(QFrame):
    """검사/진단/정리를 각각 독립된 드롭 타겟으로 만든 카드(2026-09-10, 사용자
    제안 — "3영역 다 드래그드랍 넣는건 어때"). 위쪽에 따로 있던 SelectionCard
    (공용 드롭존)가 없어지고, 이 카드 자체에 파일을 끌어놓으면 바로 그 액션이
    시작된다는 컨셉 — B안의 "드롭 → 선택" 2단계가 "드롭 = 실행" 1단계로
    줄어든다. 대신 타겟 하나하나가 작아지는 트레이드오프가 있어서, 드래그
    중엔 지금 위에 올라온 카드를 점선 테두리로 강조해 어디에 놓일지 명확히
    보여준다(set_drag_active로 시뮬레이션 — 실제로는 dragEnterEvent에서 켬)."""

    def __init__(self, icon_pixmap: QPixmap, title: str, desc: str, emphasize: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self._emphasize = emphasize
        self._active = False
        self.setMinimumHeight(96)
        self._apply_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        icon_label = QLabel()
        icon_label.setFixedSize(52, 52)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"background-color: {COLORS['selection']}; border-radius: 26px;")
        icon_label.setPixmap(icon_pixmap)
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        text_col.addWidget(title_label)
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px; background: transparent;")
        text_col.addWidget(desc_label)
        layout.addLayout(text_col, 1)

        hint_label = QLabel("여기로 끌어놓기\n또는 클릭")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 10.5px; background: transparent;")
        layout.addWidget(hint_label)

    def set_drag_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(
                f"QFrame#Card {{ border: 2px dashed {COLORS['primary']}; border-radius: 14px; "
                f"background-color: {COLORS['selection']}; }}"
            )
            return
        border = f"2px solid {COLORS['primary']}" if self._emphasize else f"1px solid {COLORS['border']}"
        self.setStyleSheet(
            f"QFrame#Card {{ border: {border}; border-radius: 14px; background-color: {COLORS['surface']}; }}"
        )


def _brand_header() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    title = QLabel("PicMedic")
    title.setStyleSheet("font-size: 20px; font-weight: 700;")
    row.addWidget(title)
    subtitle = QLabel("사진을 치료해줄게요")
    subtitle.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12.5px; padding-top: 6px;")
    row.addWidget(subtitle)
    row.addStretch(1)
    return row


def _section_container() -> tuple[QWidget, QVBoxLayout]:
    content = QWidget()
    content.setFixedWidth(CONTENT_WIDTH)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(20)
    return content, layout


def _wrap(content: QWidget) -> QWidget:
    outer_widget = QWidget()
    outer_widget.setStyleSheet(f"background-color: {COLORS['bg']};")
    outer = QVBoxLayout(outer_widget)
    outer.setContentsMargins(48, 48, 48, 48)
    outer.setAlignment(Qt.AlignTop)
    outer.addWidget(content, alignment=Qt.AlignHCenter)
    outer.addStretch(1)
    return outer_widget


# --- Concept A: 드롭존 + 3개 액션 카드 항상 같이 보임 ------------------------

def build_concept_a() -> QWidget:
    content, layout = _section_container()
    layout.addLayout(_brand_header())

    selection = SelectionCard()
    layout.addWidget(selection)

    hint = QLabel("무엇을 할까요? — 먼저 위에서 사진을 넣고 아래에서 골라주세요.")
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    layout.addWidget(hint)

    cards_row = QHBoxLayout()
    cards_row.setSpacing(12)
    cards_row.addWidget(ActionCard(_scan_icon(COLORS["primary"]), "검사", "손상·형식 오류를 찾아요", emphasize=True))
    cards_row.addWidget(ActionCard(_diagnose_icon(COLORS["primary"]), "진단", "화질(흐림·노이즈)을 봐요"))
    cards_row.addWidget(ActionCard(_organize_icon(COLORS["primary"]), "정리", "중복·날짜·고양이로 정리해요"))
    layout.addLayout(cards_row)

    return _wrap(content)


# --- Concept B: 드롭 전엔 드롭존만, 드롭 후 선택 카드가 나타남 ----------------

def build_concept_b(after_drop: bool) -> QWidget:
    content, layout = _section_container()
    layout.addLayout(_brand_header())

    selection = SelectionCard()
    layout.addWidget(selection)

    if not after_drop:
        hint = QLabel("파일이나 폴더를 끌어놓거나 선택하면 다음 단계를 고를 수 있어요.")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return _wrap(content)

    picked = QFrame()
    picked.setObjectName("Card")
    picked_layout = QHBoxLayout(picked)
    picked_layout.setContentsMargins(16, 12, 16, 12)
    picked_label = QLabel("📁 선택됨 · 가족사진_2024 폴더 (사진 128장)")
    picked_label.setStyleSheet("font-weight: 600; font-size: 12.5px;")
    picked_layout.addWidget(picked_label)
    picked_layout.addStretch(1)
    change_btn = QPushButton("바꾸기")
    picked_layout.addWidget(change_btn)
    layout.addWidget(picked)

    chooser_title = QLabel("이 사진들로 무엇을 할까요?")
    chooser_title.setStyleSheet("font-weight: 700; font-size: 14px;")
    layout.addWidget(chooser_title)

    cards_row = QHBoxLayout()
    cards_row.setSpacing(12)
    cards_row.addWidget(ActionCard(_scan_icon(COLORS["primary"]), "검사", "손상·형식 오류를 찾아요", emphasize=True))
    cards_row.addWidget(ActionCard(_diagnose_icon(COLORS["primary"]), "진단", "화질(흐림·노이즈)을 봐요"))
    cards_row.addWidget(ActionCard(_organize_icon(COLORS["primary"]), "정리", "중복·날짜·고양이로 정리해요"))
    layout.addLayout(cards_row)

    return _wrap(content)


# --- Concept C: 상단 탭(세그먼트)으로 먼저 모드를 고르고, 드롭존이 그에 맞춰 반응 --

def build_concept_c() -> QWidget:
    content, layout = _section_container()
    layout.addLayout(_brand_header())

    tabs = QFrame()
    tabs.setObjectName("Card")
    tabs.setStyleSheet(
        f"QFrame#Card {{ border-radius: 12px; background-color: {COLORS['selection']}; }}"
    )
    tabs_layout = QHBoxLayout(tabs)
    tabs_layout.setContentsMargins(4, 4, 4, 4)
    tabs_layout.setSpacing(4)

    def make_tab(label: str, active: bool) -> QLabel:
        tab = QLabel(label)
        tab.setAlignment(Qt.AlignCenter)
        if active:
            tab.setStyleSheet(
                f"background-color: {COLORS['surface']}; border-radius: 9px; padding: 10px; "
                f"font-weight: 700; font-size: 13px; color: {COLORS['primary_hover']};"
            )
        else:
            tab.setStyleSheet(
                f"padding: 10px; font-size: 13px; color: {COLORS['text_secondary']};"
            )
        return tab

    tabs_layout.addWidget(make_tab("검사", True), 1)
    tabs_layout.addWidget(make_tab("진단", False), 1)
    tabs_layout.addWidget(make_tab("정리", False), 1)
    layout.addWidget(tabs)

    mode_desc = QLabel("선택한 사진/폴더에서 손상되거나 형식이 잘못된 파일을 찾아 복구까지 도와드려요.")
    mode_desc.setWordWrap(True)
    mode_desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    layout.addWidget(mode_desc)

    selection = SelectionCard()
    layout.addWidget(selection)

    return _wrap(content)


# --- Concept E (B안 변형): 공용 드롭존 없이, 카드 3개가 각자 드롭 타겟 ------

def build_concept_e(drag_active_index: int | None = None) -> QWidget:
    content, layout = _section_container()
    layout.addLayout(_brand_header())

    hint = QLabel("사진/폴더를 원하는 카드에 바로 끌어놓으세요 — 클릭해서 선택할 수도 있어요.")
    hint.setWordWrap(True)
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
    layout.addWidget(hint)

    cards = [
        DropActionCard(_scan_icon(COLORS["primary"]), "검사", "손상·형식 오류를 찾아요", emphasize=True),
        DropActionCard(_diagnose_icon(COLORS["primary"]), "진단", "화질(흐림·노이즈)을 봐요"),
        DropActionCard(_organize_icon(COLORS["primary"]), "정리", "중복·날짜·고양이로 정리해요"),
    ]
    for idx, card in enumerate(cards):
        if drag_active_index is not None:
            card.set_drag_active(idx == drag_active_index)
        layout.addWidget(card)

    bottom_row = QHBoxLayout()
    bottom_row.setSpacing(10)
    trash_btn = QPushButton("임시 휴지통")
    bottom_row.addWidget(trash_btn)
    bottom_row.addStretch(1)
    layout.addLayout(bottom_row)

    return _wrap(content)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)

    jobs = [
        ("concept_a.png", build_concept_a()),
        ("concept_b_before.png", build_concept_b(after_drop=False)),
        ("concept_b_after.png", build_concept_b(after_drop=True)),
        ("concept_c.png", build_concept_c()),
        ("concept_e.png", build_concept_e()),
        ("concept_e_dragging.png", build_concept_e(drag_active_index=2)),
    ]
    for filename, widget in jobs:
        widget.adjustSize()
        widget.resize(CONTENT_WIDTH + 96, widget.sizeHint().height())
        pixmap = widget.grab()
        pixmap.save(str(OUT_DIR / filename))
        print(f"saved {filename} ({pixmap.width()}x{pixmap.height()})")


if __name__ == "__main__":
    main()
