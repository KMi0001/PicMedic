"""
gui/common_dialogs.py

여러 화면에서 공통으로 쓰는 카드형 팝업(DESIGN.md "팝업/다이얼로그 패턴").
원래 각 화면에 로컬로 두던 것(gui/recovery_screen.py의 _confirm_dialog,
gui/scan_session_window.py의 _info_dialog)을, 세 번째 화면(gui/duplicate_screen.py)
에서도 같은 게 필요해지면서 이곳으로 모았다 — DESIGN.md에 적어둔 "같은 요구가
2번째로 생기면 공용 컴포넌트로 옮긴다" 원칙 그대로.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

from gui.icons import status_icon_pixmap
from gui.theme import COLORS


def question_icon_pixmap(accent: str, size: int = 48) -> QPixmap:
    """확인 필요 팝업 아이콘 — gui/icons.py의 공용 아이콘("question")을 이 이름으로도
    계속 쓸 수 있게 얇게 감싼 것. 다른 화면(quality_enhance_dialog.py 등)이
    `from gui.common_dialogs import question_icon_pixmap`로 그대로 가져다 쓰고 있어
    이름은 유지한다."""
    return status_icon_pixmap("question", accent, size)


def info_icon_pixmap(color: str, size: int = 32) -> QPixmap:
    """안내(정보) 팝업 아이콘 — gui/icons.py의 공용 아이콘("info")을 감싼 것."""
    return status_icon_pixmap("info", color, size)


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
    """진행 팝업 헤더 아이콘 — gui/icons.py의 공용 아이콘("progress")을 감싼 것."""
    return status_icon_pixmap("progress", accent, size)


class _SpinnerWidget(QWidget):
    """진행 팝업 헤더의 회전 스피너 — 유니코드 문자(◐◓◑◒)를 갈아끼우던 예전
    방식 대신 QPainter로 직접 그린 원형 링을 돌린다("너무 후져 보인다"는
    피드백, 2026-09-18) — DESIGN.md 아이콘 원칙(이모지/특수문자 대신 항상
    벡터로 직접 그림)과 맞춘다."""

    def __init__(self, color: str, size: int = 18, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._angle = 0
        self.setFixedSize(size, size)

    def set_angle(self, angle: int) -> None:
        self._angle = angle % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color)
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        margin = pen.widthF() / 2 + 1
        rect = QRectF(margin, margin, self.width() - margin * 2, self.height() - margin * 2)
        # 원 전체가 아니라 270도짜리 호 하나만 그려서 계속 돌리면 "로딩 중"
        # 링 느낌이 난다. Qt 각도 단위는 1/16도, 양수가 반시계 방향이라
        # 시계 방향으로 돌아가 보이게 부호를 뒤집는다.
        start_angle = -self._angle * 16
        span_angle = -270 * 16
        painter.drawArc(rect, start_angle, span_angle)


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
        # 원형(회전) 스피너 — 2026-09-17, 사용자 리포트: 파일이 아주 많으면
        # (2만 개+) 항목 하나 처리에 걸리는 시간이 늘어나면서 퍼센트 막대가
        # 한동안 안 움직이는 것처럼 보여서 "멈춘 줄 알았다"는 피드백. 진행률
        # 신호가 뜸하게 와도 이 위젯만은 파일 처리 속도와 무관하게 계속
        # 회전해서 "죽지 않았다"를 보여준다 — 실제 진행 신호(update_progress)에
        # 기대지 않고 자체 QTimer로 애니메이션한다.
        self._spinner = _SpinnerWidget(COLORS["primary"])
        header_row.addWidget(self._spinner)
        self._spinner_angle = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(20)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self.finished.connect(lambda _result: self._spinner_timer.stop())
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
        self._spinner_angle = 0
        self._spinner.set_angle(0)
        self._spinner_timer.start()

    def _advance_spinner(self) -> None:
        self._spinner_angle = (self._spinner_angle + 8) % 360
        self._spinner.set_angle(self._spinner_angle)

    def update_progress(self, current: int, total: int, filename: str):
        pct = int((current / total) * 100) if total else 0
        self.bar.setValue(pct)
        # 파일명(특히 긴 숫자 나열 파일명)엔 줄바꿈될 공백이 없어서 setWordWrap만으론
        # 못 끊기고 고정폭 팝업 밖으로 삐져나갔다(2026-09-10, 사용자 리포트) — 파일명
        # 줄과 "처리 중..." 줄을 아예 나눠서(원래도 공백 때문에 사실상 이렇게 두 줄로
        # 보였다), 파일명 줄만 그 폭에 맞게 가운데를 말줄임표로 줄인다. 전체 문구는
        # 툴팁으로 남겨 필요하면 볼 수 있게 한다.
        suffix = f"처리 중... ({current}/{total})"
        metrics = self.status_label.fontMetrics()
        elided_filename = metrics.elidedText(filename, Qt.ElideMiddle, max(self.status_label.width(), 0))
        self.status_label.setText(f"{elided_filename}\n{suffix}")
        self.status_label.setToolTip(f"{filename} {suffix}")

    def _on_cancel_clicked(self):
        # 이미 처리 중인 작업은 끝까지 끝내야 하니 버튼을 바로 잠그고 진행 중임을 알린다
        # — 워커가 다음 단계로 넘어가기 전에 취소 여부를 체크해서 멈춘다.
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("취소하는 중...")
        self.status_label.setText("현재 작업까지 마치고 중단합니다...")
        self.cancel_requested.emit()
