"""
gui/common_dialogs.py

여러 화면에서 공통으로 쓰는 카드형 팝업(DESIGN.md "팝업/다이얼로그 패턴").
원래 각 화면에 로컬로 두던 것(gui/recovery_screen.py의 _confirm_dialog,
gui/scan_session_window.py의 _info_dialog)을, 세 번째 화면(gui/duplicate_screen.py)
에서도 같은 게 필요해지면서 이곳으로 모았다 — DESIGN.md에 적어둔 "같은 요구가
2번째로 생기면 공용 컴포넌트로 옮긴다" 원칙 그대로.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

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


def info_dialog_with_folder(parent: QWidget, message: str, folder_path: str) -> None:
    """info_dialog()에 "폴더 열기" 버튼을 하나 더 붙인 버전 — 결과가 파일로
    저장됐을 때(날짜별 정리, 복구 등) 그 폴더를 바로 열어볼 수 있게 한다."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")
    dialog.setWindowModality(Qt.WindowModal)

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(info_icon_pixmap(COLORS["primary"]))
    layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    msg_label = QLabel(message)
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(260)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    open_folder_btn = QPushButton("폴더 열기")
    btn_row.addWidget(open_folder_btn)
    ok_btn = QPushButton("확인")
    ok_btn.setObjectName("Primary")
    ok_btn.setDefault(True)
    btn_row.addWidget(ok_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    def open_folder():
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    open_folder_btn.clicked.connect(open_folder)
    ok_btn.clicked.connect(dialog.accept)
    dialog.exec()


def progress_icon_pixmap(accent: str, size: int = 22) -> QPixmap:
    """진행 팝업 헤더 아이콘: 같은 색 원 + 흰색 점 3개("처리 중")로, 다른 팝업
    아이콘(확인/안내 등)과 같은 스타일을 유지한다 — 회전 애니메이션 없이 정적인
    아이콘이라 '스피너'보다는 '진행 중임을 나타내는 점'으로 단순화."""
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
    painter.setBrush(QColor(accent))
    painter.drawEllipse(0, 0, size, size)

    painter.setBrush(QColor("white"))
    for x in (6.5, 12, 17.5):
        painter.drawEllipse(pt(x, 12), 1.6 * inner_scale, 1.6 * inner_scale)

    painter.end()
    return pixmap


class ProgressDialog(QDialog):
    """오래 걸리는 작업(복구/변환/화질 개선 등) 진행 중 뜨는 모달 팝업. 작업이
    끝날 때까지 화면(설정/뒤로가기 등)을 건드릴 수 없게 막는다 — PRD_MVP우선순위.md
    갭 #9(진행 중 설정 잠금 필요)를 "모든 컨트롤을 개별적으로 비활성화" 대신
    모달 팝업 하나로 해결한다. 창 자체의 닫기(X) 버튼은 없앤다 — 취소는 반드시
    아래 "취소" 버튼(cancel_requested)을 거쳐서 워커 쪽 취소 로직으로 이어지게
    하기 위함. 원래 gui/recovery_screen.py에만 있었는데, gui/detail_screen.py의
    화질 개선에도 같은 게 필요해지면서 공용으로 옮김(DESIGN.md 원칙)."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        # ApplicationModal이 아니라 이 창(세션)만 막는다 — 다른 검사 세션 창은
        # 계속 조작 가능해야 "다중 검사" 취지에 맞는다.
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        icon_label = QLabel()
        icon_label.setPixmap(progress_icon_pixmap(COLORS["primary"]))
        header_row.addWidget(icon_label)
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        header_row.addWidget(self.title_label)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        self.bar = QProgressBar()
        layout.addWidget(self.bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.status_label)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignRight)

    def start(self, title: str):
        self.title_label.setText(title)
        self.bar.setValue(0)
        self.status_label.setText("준비 중...")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("취소")

    def update_progress(self, current: int, total: int, filename: str):
        pct = int((current / total) * 100) if total else 0
        self.bar.setValue(pct)
        self.status_label.setText(f"{filename} 처리 중... ({current}/{total})")

    def _on_cancel_clicked(self):
        # 이미 처리 중인 작업은 끝까지 끝내야 하니 버튼을 바로 잠그고 진행 중임을 알린다
        # — 워커가 다음 단계로 넘어가기 전에 취소 여부를 체크해서 멈춘다.
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("취소하는 중...")
        self.status_label.setText("현재 작업까지 마치고 중단합니다...")
        self.cancel_requested.emit()
