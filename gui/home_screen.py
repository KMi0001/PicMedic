"""
gui/home_screen.py

PRD 16장 "Screen 01 — Home" 구현.

2026-09-10, 사용자 요청으로 재구성: "최근 검사" 목록을 없애고, 검사/진단/정리
3개 액션을 각각 독립된 드래그앤드롭 카드로 노출했었다(experiments/
home_redesign_prototype에서 스크린샷으로 검증받은 안, B안 변형).

2026-09-13, 사용자 요청으로 "검사"와 "정리"를 다시 하나로 합쳤다 — 예전엔
"정리"가 스캔 없이 곧장 정리 허브 화면으로 랜딩해서(gui/scan_session_window.py::
ScanSessionWindow의 land_on_organize), 허브의 카드(중복/유사/날짜별/도시별)
중 하나를 실제로 고를 때 그제서야 전체 스캔을 시작했다(사진 3만 장 규모에서
"정리"가 항상 무거운 진단 스캔부터 돌던 문제 회피용). 지금은 검사 결과
화면 자체에 정리 카드가 합쳐져 있어서(gui/result_screen.py) 그 지연 스캔이
필요 없어졌고, 파일/폴더를 고르면 바로 전체 스캔 → 검사 결과+정리 화면
하나로 간다. "진단"은 원래도 스캔 없이 사진 한 장만 바로 분석하는 별도
흐름이었고 그대로 유지 — 카드에 여러 장/폴더가 오면 "한 장만" 안내만
새로 추가했다.

"최근 검사"와 함께 있던 복구 결과 재방문 기능(record_recovery_outcome)도
같이 없앴다 — 복구 직후 폴더 열기는 gui/recovery_result_screen.py에 이미
있어서 핵심 기능 손실은 없다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    Signal,
    QSettings,
    QStandardPaths,
    QPointF,
    QRectF,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    QUrl,
)
from PySide6.QtGui import QCursor, QPixmap, QPainter, QPen, QColor, QBrush, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
    QDialog,
    QMenu,
    QAbstractButton,
)

from core.scanner import SCANNABLE_EXTENSIONS
from gui import theme
from gui.common_dialogs import info_dialog
from gui.convert_dialog import run_convert
from gui.help_dialog import show_help
from gui.live_photo_dialog import run_live_photo_finder
from gui.rename_dialog import run_rename
from gui.theme import COLORS
from gui.trash_screen import TrashScreen
from utils import trash
from utils.assets import asset_path

CONTENT_WIDTH = 520

# PicMedic-Web(별도 저장소)의 개인정보처리방침 — 데스크톱 프로그램은 별도
# 페이지를 만들지 않고 이 웹 페이지로 연결한다(2026-09-11). 그쪽 저장소에서
# 문구가 바뀌면 이 링크도 그대로 최신 내용을 보여준다.
PRIVACY_POLICY_URL = "https://kmi0001.github.io/PicMedic-Web/privacy-policy.html"

_IMAGE_FILTER_PATTERN = " ".join(f"*{ext}" for ext in sorted(SCANNABLE_EXTENSIONS))
IMAGE_FILE_FILTER = f"이미지 파일 ({_IMAGE_FILTER_PATTERN});;모든 파일 (*)"


def _outline_icon(color: str, size: int, draw) -> QPixmap:
    """스트로크만 있는 아웃라인 벡터 아이콘 공통 뼈대 — gui/result_screen.py::
    _outline_icon과 같은 스타일(정리 화면 아이콘들도 파일마다 이 패턴을 따로
    복붙해서 씀, 새 abstraction을 안 만드는 게 이 코드베이스 관례)."""
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




def _convert_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """변환 = 서로 반대 방향을 가리키는 화살표 두 개 — gui/recovery_screen.py::
    _convert_icon_pixmap과 같은 모양(그 화면 "복구/변환"의 "변환" 절반과
    같은 의미라 아이콘을 맞춤)."""

    def draw(p, s):
        p.drawLine(QPointF(4 * s, 8 * s), QPointF(17 * s, 8 * s))
        p.drawLine(QPointF(13 * s, 4 * s), QPointF(17 * s, 8 * s))
        p.drawLine(QPointF(13 * s, 12 * s), QPointF(17 * s, 8 * s))
        p.drawLine(QPointF(20 * s, 16 * s), QPointF(7 * s, 16 * s))
        p.drawLine(QPointF(11 * s, 12 * s), QPointF(7 * s, 16 * s))
        p.drawLine(QPointF(11 * s, 20 * s), QPointF(7 * s, 16 * s))

    return _outline_icon(color, size, draw)


def _live_photo_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """라이브 포토 = 사진 프레임 안에 재생(▶) 표시 — "움직이는 사진"이라는 의미."""

    def draw(p, s):
        p.drawRoundedRect(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 3 * s, 3 * s)
        p.drawLine(QPointF(9 * s, 7 * s), QPointF(9 * s, 17 * s))
        p.drawLine(QPointF(9 * s, 7 * s), QPointF(16 * s, 12 * s))
        p.drawLine(QPointF(9 * s, 17 * s), QPointF(16 * s, 12 * s))

    return _outline_icon(color, size, draw)


def _folder_photo_icon_pixmap(color: str, size: int = 44) -> QPixmap:
    """홈 화면 드롭존(PhotoFolderDropZone) 아이콘 — 폴더 오른쪽 아래에 사진
    배지가 겹쳐 올라간 모양(2026-09-18, 사용자가 5개 후보 중 선택). 배지
    자리를 카드 배경색으로 먼저 "지운" 뒤 그 위에 배지를 그려서, 폴더 선이
    배지 밑으로 자연스럽게 가려지게 한다(겹친 선이 그대로 비치던 초안 피드백
    반영) — 이 배경색은 PhotoFolderDropZone의 평상시 배경(COLORS['surface'])과
    맞춰뒀다."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.15 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def p(x, y):
        return QPointF(x * scale, y * scale)

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    # 폴더 외곽선(왼쪽 위 탭 + 몸체)
    painter.drawLine(p(3, 7), p(3, 18))
    painter.drawLine(p(3, 18), p(15, 18))
    painter.drawLine(p(15, 18), p(15, 9))
    painter.drawLine(p(15, 9), p(9, 9))
    painter.drawLine(p(9, 9), p(7, 7))
    painter.drawLine(p(7, 7), p(3, 7))

    # 사진 배지가 덮을 자리를 배경색으로 지운다(배지보다 살짝 크게)
    badge_x, badge_y, badge_w, badge_h = 11.5, 11.5, 9.5, 7.5
    pad = 0.9
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(COLORS["surface"]))
    painter.drawRoundedRect(r(badge_x - pad, badge_y - pad, badge_w + pad * 2, badge_h + pad * 2), 1.6 * scale, 1.6 * scale)

    # 사진 배지 — 프레임 + 해 + 산
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(r(badge_x, badge_y, badge_w, badge_h), 1.2 * scale, 1.2 * scale)
    painter.drawEllipse(r(badge_x + 1, badge_y + 1, badge_w * 0.22, badge_w * 0.22))
    painter.drawLine(
        p(badge_x + badge_w * 0.12, badge_y + badge_h * 0.85), p(badge_x + badge_w * 0.5, badge_y + badge_h * 0.3)
    )
    painter.drawLine(
        p(badge_x + badge_w * 0.5, badge_y + badge_h * 0.3), p(badge_x + badge_w * 0.9, badge_y + badge_h * 0.85)
    )

    painter.end()
    return pixmap


def _rename_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """이름 일괄변환 = 이름표(태그) 모양 + 안의 글자 줄 — "이름을 새로 단다"는 의미."""

    def draw(p, s):
        p.drawLine(QPointF(4 * s, 5 * s), QPointF(15 * s, 5 * s))
        p.drawLine(QPointF(15 * s, 5 * s), QPointF(20 * s, 12 * s))
        p.drawLine(QPointF(20 * s, 12 * s), QPointF(15 * s, 19 * s))
        p.drawLine(QPointF(15 * s, 19 * s), QPointF(4 * s, 19 * s))
        p.drawLine(QPointF(4 * s, 19 * s), QPointF(4 * s, 5 * s))
        p.drawEllipse(QRectF(6.5 * s, 10.5 * s, 3 * s, 3 * s))
        p.drawLine(QPointF(12 * s, 9 * s), QPointF(17 * s, 9 * s))
        p.drawLine(QPointF(12 * s, 13 * s), QPointF(17 * s, 13 * s))

    return _outline_icon(color, size, draw)


class ThemeToggle(QAbstractButton):
    """다크모드 on/off용 iOS 스타일 토글 스위치. 트랙/노브 색을 매 paintEvent마다
    COLORS에서 읽으므로, 테마가 바뀌면(다른 창에서든) 다음 repaint에 알아서
    새 색으로 그려진다 — 이 위젯 자체를 위한 refresh는 따로 필요 없다."""

    _WIDTH = 44
    _HEIGHT = 24
    _MARGIN = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self._knob_pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"knob_pos", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate_to)

    def _animate_to(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knob_pos = Property(float, _get_knob_pos, _set_knob_pos)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._knob_pos = 1.0 if checked else 0.0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        track_off = QColor(COLORS["border"])
        track_on = QColor(COLORS["primary"])
        painter.setBrush(QBrush(self._blend(track_off, track_on, self._knob_pos)))
        painter.drawRoundedRect(self.rect(), self._HEIGHT / 2, self._HEIGHT / 2)

        knob_d = self._HEIGHT - self._MARGIN * 2
        travel = self._WIDTH - knob_d - self._MARGIN * 2
        x = self._MARGIN + travel * self._knob_pos
        painter.setBrush(QBrush(QColor(COLORS["surface"])))
        painter.drawEllipse(QRectF(x, self._MARGIN, knob_d, knob_d))
        painter.end()

    @staticmethod
    def _blend(c1: QColor, c2: QColor, t: float) -> QColor:
        return QColor(
            int(c1.red() + (c2.red() - c1.red()) * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue() + (c2.blue() - c1.blue()) * t),
        )


class HelpButton(QAbstractButton):
    """헤더의 "사용 안내" 버튼 — 원 테두리 안에 "?"를 그린다. 색은 매 paintEvent마다
    COLORS에서 읽으므로 ThemeToggle처럼 다크모드 토글 후 따로 refresh가 필요 없다."""

    _SIZE = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse()
        color = QColor(COLORS["primary"] if hovered else COLORS["muted"])
        pen = QPen(color)
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(1.5, 1.5, self._SIZE - 3, self._SIZE - 3))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, "?")
        painter.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class DropActionCard(QFrame):
    """액션 카드(현재는 "변환") — 독립된 드래그앤드롭 타겟이자 클릭 진입점이다
    (2026-09-10, 사용자 요청으로 공용 드롭존을 없애고 카드마다 드롭 기능을
    넣는 안으로 확정 — experiments/home_redesign_prototype에서 스크린샷으로
    검증됨). 드래그가 카드 위에 있는 동안만 점선 테두리로 강조해서 "여기
    놓으면 이 액션"이라는 걸 명확히 한다. 2026-09-13: "검사"/"진단" 카드는
    PhotoFolderDropZone 하나로 합쳐지면서 이 클래스를 쓰는 건 "변환"만 남았다."""

    paths_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, icon_pixmap: QPixmap, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self._apply_style(active=False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(52, 52)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet(f"background-color: {COLORS['selection']}; border-radius: 26px;")
        self.icon_label.setPixmap(icon_pixmap)
        layout.addWidget(self.icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        text_col.addWidget(title_label)
        self.desc_label = QLabel(desc)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11.5px; background: transparent;"
        )
        text_col.addWidget(self.desc_label)
        layout.addLayout(text_col, 1)

        self.hint_label = QLabel("여기로 끌어놓기\n또는 클릭")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 10.5px; background: transparent;")
        layout.addWidget(self.hint_label)

    def refresh_theme(self, icon_pixmap: QPixmap) -> None:
        """다크모드 토글 직후 호출 — 인라인 setStyleSheet로 색을 굳혀놓은
        라벨들과 COLORS['primary']로 그려둔 아이콘 픽스맵을 새 팔레트로 다시
        칠한다(QFrame#Card 테두리는 _apply_style이 처리)."""
        self._apply_style(active=False)
        self.icon_label.setStyleSheet(f"background-color: {COLORS['selection']}; border-radius: 26px;")
        self.icon_label.setPixmap(icon_pixmap)
        self.desc_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11.5px; background: transparent;"
        )
        self.hint_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 10.5px; background: transparent;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_style(active=True)

    def dragLeaveEvent(self, event):
        self._apply_style(active=False)

    def dropEvent(self, event):
        self._apply_style(active=False)
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.toLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _apply_style(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                f"QFrame#Card {{ border: 2px dashed {COLORS['primary']}; border-radius: 14px; "
                f"background-color: {COLORS['selection']}; }}"
            )
            return
        self.setStyleSheet(
            f"QFrame#Card {{ border: 1px solid {COLORS['border']}; border-radius: 14px; "
            f"background-color: {COLORS['surface']}; }}"
        )


class PhotoFolderDropZone(QFrame):
    """2026-09-13, 사용자 요청 — "검사"와 "진단" 카드를 없애고 그 자리를
    사진·폴더를 놓는 단순한 영역 하나로 채운다. 뭘 넣든(사진 한 장이든 폴더든)
    항상 검사(→검사 결과+정리 화면, gui/scan_session_window.py)로 이어진다.
    (같은 날 후속: "사진 진단" 기능 자체도 완전히 제거되어 — 화질개선 등
    실행형 복원 기능이 다 빠진 뒤로는 진단 결과가 가리킬 데가 없어졌음 —
    지금은 진입점만 합쳐진 게 아니라 기능 자체가 없다.)
    DropActionCard와 같은 드래그앤드롭 메커니즘을 쓰되, 카드 2개 자리를
    차지하도록 아이콘·설명 없이 넉넉한 빈 영역으로 단순하게 둔다."""

    paths_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)
        self._apply_style(active=False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent;")
        self.icon_label.setPixmap(_folder_photo_icon_pixmap(COLORS["primary"]))
        layout.addWidget(self.icon_label)

        title = QLabel("사진 · 폴더")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: 700; background: transparent;")
        layout.addWidget(title)

        self.hint_label = QLabel("여기로 끌어놓거나 클릭해서 선택하세요")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self.hint_label)

    def refresh_theme(self) -> None:
        self._apply_style(active=False)
        self.icon_label.setPixmap(_folder_photo_icon_pixmap(COLORS["primary"]))
        self.hint_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_style(active=True)

    def dragLeaveEvent(self, event):
        self._apply_style(active=False)

    def dropEvent(self, event):
        self._apply_style(active=False)
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.toLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _apply_style(self, active: bool) -> None:
        # 이 영역이 이제 홈 화면의 유일한 주요 진입점이라(2026-09-13) 대기
        # 상태에서도 늘 강조색 점선 테두리로 둔다 — 드래그 중엔 배경만 더 짙게.
        bg = COLORS["selection"] if active else COLORS["surface"]
        self.setStyleSheet(
            f"QFrame#Card {{ border: 2px dashed {COLORS['primary']}; border-radius: 14px; "
            f"background-color: {bg}; }}"
        )


class HomeScreen(QWidget):
    """검사(정리 포함)·진단·변환 중 뭘 할지 고르는 첫 화면."""

    paths_chosen = Signal(list)  # 검사 — ScanSessionWindow를 열고 끝나면 검사 결과+정리 화면으로

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PicMedic", "PicMedic")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.setAlignment(Qt.AlignTop)

        content = QWidget()
        content.setFixedWidth(CONTENT_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        brand_icon = QLabel()
        brand_icon.setFixedSize(44, 44)
        brand_icon.setPixmap(
            QPixmap(asset_path("icon.png")).scaled(
                44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        header_row.addWidget(brand_icon, alignment=Qt.AlignVCenter)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        title = QLabel("PicMedic")
        title.setStyleSheet("font-size: 20px; font-weight: 700; margin: 0; padding: 0;")
        self.subtitle_label = QLabel("사진을 치료해줄게요")
        self.subtitle_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12.5px; margin: 0; padding: 0;"
        )
        brand_text.addWidget(title)
        brand_text.addWidget(self.subtitle_label)
        header_row.addLayout(brand_text)
        header_row.setAlignment(brand_text, Qt.AlignVCenter)
        header_row.addStretch(1)

        self.help_btn = HelpButton()
        self.help_btn.setToolTip("사용 안내")
        self.help_btn.clicked.connect(lambda: show_help(self))
        header_row.addWidget(self.help_btn, alignment=Qt.AlignVCenter)
        header_row.addSpacing(8)

        self.theme_toggle = ThemeToggle()
        self.theme_toggle.setChecked(theme.is_dark_mode())
        self.theme_toggle.setToolTip("다크 모드")
        self.theme_toggle.toggled.connect(self._on_theme_toggled)
        header_row.addWidget(self.theme_toggle, alignment=Qt.AlignVCenter)

        content_layout.addLayout(header_row)

        self.hint_label = QLabel("사진이나 폴더를 끌어놓으면 검사하고 정리까지 도와드려요.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        content_layout.addWidget(self.hint_label)

        self.drop_zone = PhotoFolderDropZone()
        self.drop_zone.paths_dropped.connect(self._on_scan_paths_chosen)
        self.drop_zone.clicked.connect(lambda: self._show_pick_menu(self._on_scan_paths_chosen))
        content_layout.addWidget(self.drop_zone)

        self.convert_card = DropActionCard(
            _convert_icon_pixmap(COLORS["primary"]),
            "변환",
            "사진 형식을 다른 형식으로 바꿔요 (여러 장도 가능)",
        )
        self.convert_card.paths_dropped.connect(self._on_convert_paths_chosen)
        self.convert_card.clicked.connect(lambda: self._show_pick_menu(self._on_convert_paths_chosen))
        content_layout.addWidget(self.convert_card)

        self.live_photo_card = DropActionCard(
            _live_photo_icon_pixmap(COLORS["primary"]),
            "라이브 포토",
            "짝 동영상이 남아있는 라이브 포토를 찾아서 내보내거나 모아줘요",
        )
        self.live_photo_card.paths_dropped.connect(self._on_live_photo_paths_chosen)
        self.live_photo_card.clicked.connect(lambda: self._show_pick_menu(self._on_live_photo_paths_chosen))
        content_layout.addWidget(self.live_photo_card)

        self.rename_card = DropActionCard(
            _rename_icon_pixmap(COLORS["primary"]),
            "이름 일괄변환",
            "사진 여러 장의 파일명을 한 번에 바꿔요 (순번 매기기 등)",
        )
        self.rename_card.paths_dropped.connect(self._on_rename_paths_chosen)
        self.rename_card.clicked.connect(lambda: self._show_pick_menu(self._on_rename_paths_chosen))
        content_layout.addWidget(self.rename_card)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        trash_btn = QPushButton("임시 휴지통")
        trash_btn.clicked.connect(self._open_trash)
        bottom_row.addWidget(trash_btn)
        bottom_row.addStretch(1)
        self.privacy_link = QLabel(f'<a href="{PRIVACY_POLICY_URL}" style="color:{COLORS["muted"]};">개인정보처리방침</a>')
        self.privacy_link.setStyleSheet("font-size: 11px; background: transparent;")
        self.privacy_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.privacy_link.setOpenExternalLinks(False)
        self.privacy_link.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        bottom_row.addWidget(self.privacy_link)
        content_layout.addLayout(bottom_row)

        outer.addWidget(content, alignment=Qt.AlignHCenter)
        outer.addStretch(1)

    def _on_theme_toggled(self, checked: bool) -> None:
        # 홈 화면은 MainWindow의 central widget이라 재생성(재진입) 없이 계속
        # 떠있으므로, 인라인 setStyleSheet/아이콘 픽스맵으로 색을 굳혀둔
        # 요소들은 여기서 직접 새로 칠해줘야 한다. 나머지 화면(검사/복구 등)은
        # 세션 창을 새로 열 때(gui/scan_session_window.py) get_stylesheet()로
        # 최신 팔레트를 받는다.
        theme.set_dark_mode(checked)
        self.subtitle_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12.5px; margin: 0; padding: 0;"
        )
        self.hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        self.drop_zone.refresh_theme()
        self.convert_card.refresh_theme(_convert_icon_pixmap(COLORS["primary"]))
        self.live_photo_card.refresh_theme(_live_photo_icon_pixmap(COLORS["primary"]))
        self.rename_card.refresh_theme(_rename_icon_pixmap(COLORS["primary"]))
        self.privacy_link.setText(
            f'<a href="{PRIVACY_POLICY_URL}" style="color:{COLORS["muted"]};">개인정보처리방침</a>'
        )

    # --- 내부 로직 -----------------------------------------------------

    def _default_browse_dir(self) -> str:
        """이전에 썼던 폴더가 있으면 그곳을, 없으면 시스템 '사진' 폴더를 기본 위치로 삼는다."""
        last = self.settings.value("last_browse_dir", "")
        if last and Path(last).exists():
            return last
        pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        return pictures or ""

    def _remember_browse_dir(self, directory: str):
        if directory:
            self.settings.setValue("last_browse_dir", directory)

    def _show_pick_menu(self, on_chosen) -> None:
        """카드를 클릭했을 때 "파일 선택"/"폴더 선택" 중 고르게 하는 작은 메뉴 —
        카드마다 버튼을 두 개씩 늘어놓으면 좁아 보여서, 클릭했을 때만 잠깐
        띄운다. 카드 모서리 고정 위치가 아니라 마우스 우클릭 컨텍스트
        메뉴처럼 커서 위치에서 뜨게 한다(2026-09-10, 사용자 리포트 — "팝업이
        어색하다")."""
        menu = QMenu(self)
        file_action = menu.addAction("파일 선택...")
        folder_action = menu.addAction("폴더 선택...")
        chosen = menu.exec(QCursor.pos())
        if chosen is file_action:
            self._pick_files(on_chosen)
        elif chosen is folder_action:
            self._pick_folder(on_chosen)

    def _pick_files(self, on_chosen) -> None:
        start_dir = self._default_browse_dir()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "사진 파일 선택 (여러 개 선택 가능)", start_dir, IMAGE_FILE_FILTER
        )
        if file_paths:
            self._remember_browse_dir(str(Path(file_paths[0]).parent))
            on_chosen(file_paths)

    def _pick_folder(self, on_chosen) -> None:
        start_dir = self._default_browse_dir()
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택", start_dir)
        if folder:
            self._remember_browse_dir(folder)
            on_chosen([folder])

    def _on_scan_paths_chosen(self, paths: list[str]):
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            self.paths_chosen.emit(valid)

    def _on_convert_paths_chosen(self, paths: list[str]):
        """검사 없이 곧장 "형식 변환"을 여는 진입점 — gui/convert_dialog.py가
        폴더를 사진 파일로 펼치고 분석까지 다 처리한다. 여러 장/폴더 다 된다."""
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            run_convert(self, valid)

    def _on_live_photo_paths_chosen(self, paths: list[str]):
        """검사 없이 곧장 "라이브 포토 찾기"를 여는 진입점 — gui/live_photo_dialog.py가
        폴더 순회부터 짝 찾기, 내보내기/정리까지 다 처리한다."""
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            run_live_photo_finder(self, valid)

    def _on_rename_paths_chosen(self, paths: list[str]):
        """검사 없이 곧장 "이름 일괄변경" 팝업을 여는 진입점 — gui/rename_dialog.py가
        폴더를 사진 파일로 펼치는 것부터 이름 바꾸기까지 다 처리한다."""
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            run_rename(self, valid)

    def _open_trash(self):
        """세션(ScanSessionWindow) 없이도 임시 휴지통을 바로 볼 수 있게 하는
        진입점. 2026-09-10부터 임시휴지통은 전역 폴더 하나가 아니라 정리했던
        폴더마다 따로 생기므로(utils/trash.py), 먼저 어느 폴더의 임시휴지통을
        볼지 "불러오기"로 고르게 한다 — 그 폴더 자체를 골라도(폴더 이름이
        "임시휴지통"), 그 폴더를 담고 있는 상위 폴더를 골라도 되게 둘 다
        받아준다."""
        start_dir = self._default_browse_dir()
        chosen = QFileDialog.getExistingDirectory(self, "임시휴지통이 있는 폴더 선택", start_dir)
        if not chosen:
            return
        chosen_path = Path(chosen)
        trash_path = (
            chosen_path
            if chosen_path.name == trash.TRASH_FOLDER_NAME
            else chosen_path / trash.TRASH_FOLDER_NAME
        )
        if not trash_path.is_dir():
            info_dialog(self, f'이 폴더에는 아직 "{trash.TRASH_FOLDER_NAME}"이 없어요.\n({chosen})')
            return
        self._remember_browse_dir(chosen)

        dialog = QDialog(self)
        dialog.setWindowTitle("임시 휴지통")
        dialog.setWindowModality(Qt.WindowModal)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        screen = TrashScreen()
        screen.set_trash_dirs([trash_path])
        screen.refresh()
        screen.back_requested.connect(dialog.accept)
        layout.addWidget(screen)
        dialog.resize(760, 560)
        dialog.exec()
        # 다이얼로그가 닫히면 screen도 곧 없어지는데, 백그라운드 썸네일 로딩이
        # 아직 도는 중일 수 있다 — 스레드가 실행 중인 채로 같이 없어지면
        # 크래시 위험이 있어서 여기서 안전하게 멈춘다.
        screen.stop_pending_work()
