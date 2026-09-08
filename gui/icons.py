"""
gui/icons.py

상태를 나타내는 벡터 아이콘 — 성공/경고/오류/건너뜀/확인 필요/안내 여섯 종류를
한 함수에서 그린다. 원래는 화면마다 거의 같은 "색 원 + 흰색 글리프" 그리기
코드를 따로 두고 있었는데(DESIGN.md 원칙: "2곳 이상에서 재사용하면 공용으로"),
버터+아이보리 리브랜딩으로 네 곳(home_screen, common_dialogs, recovery_result_screen)
전부 새 스타일로 한꺼번에 바꾸면서 여기 하나로 모았다.

새 스타일: 채도 높은 원 배경 + 흰 글리프 대신, **그 색 자체를 옅게 tint한
둥근 사각 배경 + 같은 색 선(stroke) 글리프** — 배경과 글리프가 톤온톤이라
배달앱 뱃지처럼 알록달록해 보이지 않는다. tint는 고정 색상표를 안 두고
accent 색을 surface(카드 배경)와 블렌드해서 그때그때 계산한다 — 어떤 accent
색이 들어와도(브랜드색이 나중에 또 바뀌어도) 그대로 맞는 tint가 나온다.

비율은 기존 아이콘들과 동일: 24px 기준 안쪽 글리프 13px(13/24), 중앙 정렬.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap

from gui.theme import COLORS

_TINT_AMOUNT = 0.16  # accent 색을 surface에 섞는 비율 — 낮을수록 더 옅어짐


def _tint(accent: QColor) -> QColor:
    base = QColor(COLORS["surface"])
    r = base.red() + (accent.red() - base.red()) * _TINT_AMOUNT
    g = base.green() + (accent.green() - base.green()) * _TINT_AMOUNT
    b = base.blue() + (accent.blue() - base.blue()) * _TINT_AMOUNT
    return QColor(int(r), int(g), int(b))


def status_icon_pixmap(kind: str, accent: str, size: int = 24) -> QPixmap:
    """kind: "success"(체크) / "warning"(느낌표) / "error"(x) / "skip"(대시) /
    "question"(물음표) / "info"(i) / "progress"(점 3개). accent는 글리프와 tint
    계산에 쓰는 기준색(보통 COLORS['success']처럼 상태색, 확인 필요/안내/진행은
    COLORS['primary'])."""
    color = QColor(accent)
    tint = _tint(color)
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    def pt(x: float, y: float) -> QPointF:
        return QPointF(offset + x * inner_scale, offset + y * inner_scale)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(Qt.NoPen)
    painter.setBrush(tint)
    radius = size * 0.3
    painter.drawRoundedRect(0, 0, size, size, radius, radius)

    pen = QPen(color)
    pen.setWidthF(2 * inner_scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if kind == "success":
        path = QPainterPath()
        path.moveTo(pt(5, 12.5))
        path.lineTo(pt(9.5, 17))
        path.lineTo(pt(19, 7))
        painter.drawPath(path)
    elif kind == "warning":
        tri = QPainterPath()
        tri.moveTo(pt(12, 4.5))
        tri.lineTo(pt(21.5, 20.5))
        tri.lineTo(pt(2.5, 20.5))
        tri.closeSubpath()
        painter.drawPath(tri)
        painter.drawLine(pt(12, 10.3), pt(12, 15.3))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(pt(12, 17.8), 1.0 * inner_scale, 1.0 * inner_scale)
    elif kind == "error":
        painter.drawLine(pt(6.5, 6.5), pt(17.5, 17.5))
        painter.drawLine(pt(17.5, 6.5), pt(6.5, 17.5))
    elif kind == "skip":
        painter.drawLine(pt(6.5, 12), pt(17.5, 12))
    elif kind == "info":
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(pt(12, 6.3), 1.1 * inner_scale, 1.1 * inner_scale)
        pen = QPen(color)
        pen.setWidthF(2.4 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(pt(12, 10.8), pt(12, 17.5))
    elif kind == "question":
        painter.setFont(QFont("Segoe UI", int(icon_box * 0.62), QFont.Bold))
        painter.setPen(color)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "?")
    elif kind == "progress":
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for x in (6.5, 12, 17.5):
            painter.drawEllipse(pt(x, 12), 1.6 * inner_scale, 1.6 * inner_scale)

    painter.end()
    return pixmap
