"""
experiments/rebrand_palette_prototype/app.py

리브랜딩(민트 케어 -> 버터+블랙+아이보리 톤온톤) 프로토타입. "지금 스타일"과
"제안 스타일"을 같은 화면에 나란히 띄워서 비교한다 — 색만 바꾸는 게 아니라
아이콘 언어도 같이 바꾸자는 요청이라, 둘 다 실제로 그려서 비교해야 의미가 있음.

바뀌는 것 두 가지:
1. 팔레트 — 민트/티얼 계열 -> 버터(#D9B54A) + 아이보리(#F7F1E4) + 톤온톤 잉크
   블랙(#2A2420). 상태색(success/warning/danger)도 차가운 톤에서 버터와
   어울리는 따뜻한 톤(세이지 그린/번트 오렌지/브릭 레드)으로 같이 옮겼다.
   버터=브랜드색과 warning=주의색이 둘 다 노란 계열로 헷갈리지 않도록 warning은
   오렌지 쪽으로, 버터는 머스터드 쪽으로 확실히 갈라놨다.
2. 아이콘 — 지금은 채도 높은 원 배경 + 흰 글리프(gui/home_screen.py
   _status_icon_pixmap)라 알록달록한 배달앱 뱃지처럼 보인다는 피드백. 제안은
   옅은 톤(같은 색의 12% 정도 tint) 사각(둥근 모서리) 배경 + 그 색 그대로의
   선(stroke) 글리프 — 배경과 글리프가 "톤온톤"이라 원색 대비가 없어짐.

레이아웃/타이포/모서리 반경은 건드리지 않았다 — 이번 요청은 색+아이콘까지만.

새 의존성 없음, 본체 코드도 안 건드림. "지금 스타일" 쪽은 gui/theme.py의 실제
COLORS를 그대로 쓰고, home_screen.py의 아이콘 로직을 그대로 복제해서(원본이
화면 클래스에 묶여 있어 import 대신 로직만 옮김) 실제와 동일하게 비교한다.

실행: 저장소 루트에서 (본체와 같은 venv)
    python experiments/rebrand_palette_prototype/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS as OLD_COLORS

NEW_COLORS = {
    "bg": "#F7F1E4",
    "surface": "#FFFDF8",
    "border": "#E6DCC5",
    "text": "#2A2420",
    "text_secondary": "#7A7060",
    "primary": "#D9B54A",
    "primary_hover": "#C6A23A",
    "success": "#6E7F4E",
    "warning": "#B97A3A",
    "danger": "#A6453A",
    "muted": "#A79A82",
}

_NEW_TINT = {
    "success": "#E3E8D9",
    "warning": "#F0DDC4",
    "danger": "#EED6D2",
    "muted": "#EDE8DE",
}

_KINDS = ["success", "warning", "danger", "muted"]
_LABELS = {"success": "정상", "warning": "확인 필요", "danger": "손상", "muted": "제외"}


def _pt(offset: float, inner_scale: float, x: float, y: float) -> QPointF:
    return QPointF(offset + x * inner_scale, offset + y * inner_scale)


def _draw_glyph(painter: QPainter, kind: str, color: QColor, offset: float, inner_scale: float, width: float) -> None:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def p(x, y):
        return _pt(offset, inner_scale, x, y)

    if kind == "success":
        path = QPainterPath()
        path.moveTo(p(5, 12.5))
        path.lineTo(p(9.5, 17))
        path.lineTo(p(19, 7))
        painter.drawPath(path)
    elif kind == "warning":
        tri = QPainterPath()
        tri.moveTo(p(12, 4.5))
        tri.lineTo(p(21.5, 20.5))
        tri.lineTo(p(2.5, 20.5))
        tri.closeSubpath()
        painter.drawPath(tri)
        painter.drawLine(p(12, 10.3), p(12, 15.3))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(p(12, 17.8), 1.0 * inner_scale, 1.0 * inner_scale)
    elif kind == "danger":
        painter.drawLine(p(7, 7), p(17, 17))
        painter.drawLine(p(17, 7), p(7, 17))
    else:  # muted
        painter.drawLine(p(6.5, 12), p(17.5, 12))


def old_style_icon(kind: str, size: int = 24) -> QPixmap:
    """지금 스타일: 채도 높은 원 + 흰 글리프."""
    color = QColor(OLD_COLORS[kind])
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(0, 0, size, size)
    _draw_glyph(painter, kind, QColor("white"), offset, inner_scale, 3 * inner_scale)
    painter.end()
    return pixmap


def new_style_icon(kind: str, size: int = 24) -> QPixmap:
    """제안 스타일: 옅은 톤 사각(둥근 모서리) + 같은 색 선 글리프 — 톤온톤."""
    color = QColor(NEW_COLORS[kind])
    tint = QColor(_NEW_TINT[kind])
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(tint)
    painter.drawRoundedRect(0, 0, size, size, size * 0.3, size * 0.3)
    _draw_glyph(painter, kind, color, offset, inner_scale, 2 * inner_scale)
    painter.end()
    return pixmap


def _swatch_row(colors: dict, keys: list[str]) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for key in keys:
        chip = QFrame()
        chip.setFixedSize(64, 44)
        chip.setStyleSheet(f"background-color: {colors[key]}; border-radius: 6px; border: 1px solid rgba(0,0,0,0.1);")
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(chip)
        name = QLabel(key)
        name.setStyleSheet("font-size: 10px; color: #888;")
        name.setAlignment(Qt.AlignCenter)
        col.addWidget(name)
        wrap = QWidget()
        wrap.setLayout(col)
        layout.addWidget(wrap)
    return row


def _icon_row(icon_fn) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    for kind in _KINDS:
        col = QVBoxLayout()
        col.setSpacing(6)
        col.setAlignment(Qt.AlignCenter)
        icon_label = QLabel()
        icon_label.setPixmap(icon_fn(kind, 40))
        icon_label.setAlignment(Qt.AlignCenter)
        col.addWidget(icon_label)
        text = QLabel(_LABELS[kind])
        text.setAlignment(Qt.AlignCenter)
        text.setStyleSheet("font-size: 11px;")
        col.addWidget(text)
        wrap = QWidget()
        wrap.setLayout(col)
        layout.addWidget(wrap)
    return row


def _build_column(title: str, colors: dict, icon_fn, is_new: bool) -> QFrame:
    col = QFrame()
    col.setStyleSheet(
        f"background-color: {colors['bg']}; border-radius: 16px;"
    )
    outer = QVBoxLayout(col)
    outer.setContentsMargins(28, 24, 28, 28)
    outer.setSpacing(20)

    heading = QLabel(title)
    heading.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {colors['text']}; background: transparent;")
    outer.addWidget(heading)

    swatch_label = QLabel("색")
    swatch_label.setStyleSheet(f"font-size: 11px; color: {colors['text_secondary']}; background: transparent;")
    outer.addWidget(swatch_label)
    outer.addWidget(_swatch_row(colors, ["bg", "surface", "text", "primary", "success", "warning", "danger"]))

    card = QFrame()
    card.setStyleSheet(
        f"background-color: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 12px;"
    )
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(20, 18, 20, 18)
    card_layout.setSpacing(14)

    card_title = QLabel("검사 결과")
    card_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {colors['text']}; background: transparent;")
    card_layout.addWidget(card_title)

    icon_label = QLabel("아이콘")
    icon_label.setStyleSheet(f"font-size: 11px; color: {colors['text_secondary']}; background: transparent;")
    card_layout.addWidget(icon_label)
    card_layout.addWidget(_icon_row(icon_fn))

    btn_row = QHBoxLayout()
    primary_btn = QPushButton("복구 시작")
    text_color = colors["text"] if is_new else "white"
    primary_btn.setStyleSheet(
        f"background-color: {colors['primary']}; color: {text_color}; border: none; "
        f"border-radius: 8px; padding: 9px 18px; font-weight: 600;"
    )
    secondary_btn = QPushButton("건너뛰기")
    secondary_btn.setStyleSheet(
        f"background-color: {colors['surface']}; color: {colors['text']}; "
        f"border: 1px solid {colors['border']}; border-radius: 8px; padding: 9px 18px;"
    )
    btn_row.addWidget(secondary_btn)
    btn_row.addWidget(primary_btn)
    card_layout.addLayout(btn_row)

    outer.addWidget(card)
    outer.addStretch(1)
    return col


class PrototypeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("리브랜딩 팔레트 프로토타입 — 지금 vs 제안")
        self.resize(1180, 720)
        self.setStyleSheet("background-color: #EDEFEC;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        note = QLabel("왼쪽 = 지금 실제 팔레트/아이콘 그대로, 오른쪽 = 버터+아이보리+톤온톤 잉크 제안")
        note.setStyleSheet("font-size: 12px; color: #666;")
        outer.addWidget(note)

        cols = QHBoxLayout()
        cols.setSpacing(20)
        cols.addWidget(_build_column("지금 (민트 케어)", OLD_COLORS, old_style_icon, is_new=False))
        cols.addWidget(_build_column("제안 (버터 · 아이보리 · 톤온톤)", NEW_COLORS, new_style_icon, is_new=True))
        outer.addLayout(cols, stretch=1)


def main() -> None:
    app = QApplication(sys.argv)
    window = PrototypeWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
