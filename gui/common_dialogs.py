"""
gui/common_dialogs.py

여러 화면에서 공통으로 쓰는 카드형 팝업(DESIGN.md "팝업/다이얼로그 패턴").
원래 각 화면에 로컬로 두던 것(gui/recovery_screen.py의 _confirm_dialog,
gui/scan_session_window.py의 _info_dialog)을, 세 번째 화면(gui/duplicate_screen.py)
에서도 같은 게 필요해지면서 이곳으로 모았다 — DESIGN.md에 적어둔 "같은 요구가
2번째로 생기면 공용 컴포넌트로 옮긴다" 원칙 그대로.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget

from gui.theme import COLORS


def question_icon_pixmap(accent: str, size: int = 48) -> QPixmap:
    """확인 필요 팝업 아이콘: 최근 검사 목록 아이콘(gui/home_screen.py::_status_icon_pixmap)과
    같은 스타일(색 원 + 흰색 글리프, 이모지 폰트 미사용)로 맞춘 물음표 아이콘."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(0, 0, size, size)
    painter.setFont(QFont("Segoe UI", int(size * (13 / 24) * 0.55), QFont.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "?")
    painter.end()
    return pixmap


def info_icon_pixmap(color: str, size: int = 32) -> QPixmap:
    """안내(정보) 팝업 아이콘 — DESIGN.md 아이콘 시스템의 '안내'(i), 색 원 + 흰색
    벡터 글리프. 확인 필요(?) 아이콘과 같은 비율로 그린다."""
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    def pt(x, y):
        return QPointF(offset + x * inner_scale, offset + y * inner_scale)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, size, size)

    painter.setBrush(QColor("white"))
    painter.drawEllipse(pt(12, 6.3), 1.1 * inner_scale, 1.1 * inner_scale)
    pen = QPen(QColor("white"))
    pen.setWidthF(2.6 * inner_scale)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(pt(12, 10.8), pt(12, 17.5))

    painter.end()
    return pixmap


def confirm_dialog(
    parent: QWidget,
    message: str,
    confirm_text: str = "확인",
    cancel_text: str = "취소",
) -> bool:
    """왼쪽(취소 역할)/오른쪽(확인 역할, Primary+기본) 버튼이 있는 카드형 확인 팝업.
    확인 쪽을 누르면 True. 버튼 문구는 상황에 맞게 바꿔 쓴다 — 예:
    "유지"/"삭제" (gui/recovery_screen.py::_on_finished, 복구된 파일 유지 여부)."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")
    # ApplicationModal(기본값)이 아니라 이 창(부모 체인)만 막는다 — 여러 검사 세션
    # 창이 동시에 떠 있을 때 팝업 하나 때문에 다른 세션까지 멈추지 않게 한다.
    dialog.setWindowModality(Qt.WindowModal)

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(question_icon_pixmap(COLORS["primary"]))
    layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    msg_label = QLabel(message)
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(280)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton(cancel_text)
    confirm_btn = QPushButton(confirm_text)
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    return dialog.exec() == QDialog.Accepted


def info_dialog(parent: QWidget, message: str) -> None:
    """확인 버튼 하나뿐인 안내 팝업 — 네이티브 QMessageBox.information 대신 앱 테마에
    맞춘 카드형 다이얼로그."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")
    dialog.setWindowModality(Qt.WindowModal)  # 이 세션 창만 막고 다른 세션은 그대로 둔다

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(info_icon_pixmap(COLORS["primary"]))
    layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    msg_label = QLabel(message)
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(240)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    ok_btn = QPushButton("확인")
    ok_btn.setObjectName("Primary")
    ok_btn.setDefault(True)
    btn_row.addWidget(ok_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    ok_btn.clicked.connect(dialog.accept)
    dialog.exec()
