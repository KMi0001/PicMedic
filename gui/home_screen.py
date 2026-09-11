"""
gui/home_screen.py

PRD 16장 "Screen 01 — Home" 구현.

2026-09-10, 사용자 요청으로 재구성: "최근 검사" 목록을 없애고, 검사/진단/정리
3개 액션을 각각 독립된 드래그앤드롭 카드로 노출한다(experiments/
home_redesign_prototype에서 스크린샷으로 검증받은 안, B안 변형). "정리"는
스캔 없이 곧장 정리 허브 화면(gui/organize_hub_screen.py)으로 랜딩한다
(gui/scan_session_window.py::ScanSessionWindow의 land_on_organize) — 허브의
카드(중복/유사/날짜별/도시별) 중 하나를 실제로 고를 때 그제서야 전체
스캔을 시작하고, "고양이 찾기"는 그 스캔과 무관하게 항상 가벼운 자체 경로를
쓴다(사진 3만 장 규모에서 "정리"가 항상 무거운 진단 스캔부터 돌던 문제를
해결). "진단"은 원래도 스캔 없이 사진 한 장만 바로 분석하는 별도 흐름이었고
그대로 유지 — 카드에 여러 장/폴더가 오면 "한 장만" 안내만 새로 추가했다.

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
from gui.quality_diagnosis_dialog import run_quality_diagnosis
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


def _scan_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """검사 = 돋보기 (gui/result_screen.py::_search_icon_pixmap과 동일 모양)."""

    def draw(p, s):
        p.drawEllipse(QPointF(10.5 * s, 10.5 * s), 6.5 * s, 6.5 * s)
        p.drawLine(QPointF(15.2 * s, 15.2 * s), QPointF(20 * s, 20 * s))

    return _outline_icon(color, size, draw)


def _diagnose_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """진단 = 맥박(EKG) 선 — 화질을 "측정"한다는 인상."""

    def draw(p, s):
        pts = [(2, 13), (6, 13), (8, 7), (11, 19), (14, 5), (16, 13), (22, 13)]
        p.drawPolyline([QPointF(x * s, y * s) for x, y in pts])

    return _outline_icon(color, size, draw)


def _organize_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """정리 = 폴더 안에 가지런한 줄 — "가지런히 정리됨"의 인상."""

    def draw(p, s):
        p.drawRoundedRect(QRectF(2 * s, 6 * s, 20 * s, 14 * s), 2 * s, 2 * s)
        p.drawLine(QPointF(2 * s, 6 * s), QPointF(8 * s, 6 * s))
        for y in (11, 14.5, 18):
            p.drawLine(QPointF(6 * s, y * s), QPointF(18 * s, y * s))

    return _outline_icon(color, size, draw)


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


class DropActionCard(QFrame):
    """검사/진단/정리 액션 카드 — 각각 독립된 드래그앤드롭 타겟이자 클릭
    진입점이다(2026-09-10, 사용자 요청으로 공용 드롭존을 없애고 카드 3개
    각각에 드롭 기능을 넣는 안으로 확정 — experiments/home_redesign_prototype
    에서 스크린샷으로 검증됨). 드래그가 카드 위에 있는 동안만 점선 테두리로
    강조해서 "여기 놓으면 이 액션"이라는 걸 명확히 한다."""

    paths_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, icon_pixmap: QPixmap, title: str, desc: str, emphasize: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self._emphasize = emphasize
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
        border = f"2px solid {COLORS['primary']}" if self._emphasize else f"1px solid {COLORS['border']}"
        self.setStyleSheet(
            f"QFrame#Card {{ border: {border}; border-radius: 14px; background-color: {COLORS['surface']}; }}"
        )


class HomeScreen(QWidget):
    """검사·진단·정리 중 뭘 할지 고르는 첫 화면."""

    paths_chosen = Signal(list)        # 검사 — ScanSessionWindow를 열고 끝나면 검사 결과 화면으로
    organize_requested = Signal(list)  # 정리 — 스캔 없이 곧장 정리 허브로 랜딩(land_on_organize)

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

        self.theme_toggle = ThemeToggle()
        self.theme_toggle.setChecked(theme.is_dark_mode())
        self.theme_toggle.setToolTip("다크 모드")
        self.theme_toggle.toggled.connect(self._on_theme_toggled)
        header_row.addWidget(self.theme_toggle, alignment=Qt.AlignVCenter)

        content_layout.addLayout(header_row)

        self.hint_label = QLabel("사진/폴더를 원하는 카드에 바로 끌어놓으세요 — 클릭해서 선택할 수도 있어요.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        content_layout.addWidget(self.hint_label)

        self.scan_card = DropActionCard(
            _scan_icon_pixmap(COLORS["primary"]),
            "검사",
            "손상·형식 오류를 찾아 복구까지 도와드려요",
            emphasize=True,
        )
        self.scan_card.paths_dropped.connect(self._on_scan_paths_chosen)
        self.scan_card.clicked.connect(lambda: self._show_pick_menu(self._on_scan_paths_chosen))
        content_layout.addWidget(self.scan_card)

        self.diagnose_card = DropActionCard(
            _diagnose_icon_pixmap(COLORS["primary"]),
            "진단",
            "사진 한 장의 화질(흐림·노이즈)을 봐요",
        )
        self.diagnose_card.paths_dropped.connect(self._on_diagnose_paths_dropped)
        self.diagnose_card.clicked.connect(self._open_diagnose)
        content_layout.addWidget(self.diagnose_card)

        self.convert_card = DropActionCard(
            _convert_icon_pixmap(COLORS["primary"]),
            "변환",
            "사진 형식을 다른 형식으로 바꿔요 (여러 장도 가능)",
        )
        self.convert_card.paths_dropped.connect(self._on_convert_paths_chosen)
        self.convert_card.clicked.connect(lambda: self._show_pick_menu(self._on_convert_paths_chosen))
        content_layout.addWidget(self.convert_card)

        self.organize_card = DropActionCard(
            _organize_icon_pixmap(COLORS["primary"]),
            "정리",
            "중복·날짜·도시·고양이 찾기로 정리해요",
        )
        self.organize_card.paths_dropped.connect(self._on_organize_paths_chosen)
        self.organize_card.clicked.connect(
            lambda: self._show_pick_menu(self._on_organize_paths_chosen)
        )
        content_layout.addWidget(self.organize_card)

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
        self.scan_card.refresh_theme(_scan_icon_pixmap(COLORS["primary"]))
        self.diagnose_card.refresh_theme(_diagnose_icon_pixmap(COLORS["primary"]))
        self.convert_card.refresh_theme(_convert_icon_pixmap(COLORS["primary"]))
        self.organize_card.refresh_theme(_organize_icon_pixmap(COLORS["primary"]))
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

    def _on_organize_paths_chosen(self, paths: list[str]):
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            self.organize_requested.emit(valid)

    def _on_convert_paths_chosen(self, paths: list[str]):
        """검사 없이 곧장 "형식 변환"을 여는 진입점 — gui/convert_dialog.py가
        폴더를 사진 파일로 펼치고 분석까지 다 처리한다. 여러 장/폴더 다 된다."""
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            run_convert(self, valid)

    def _on_diagnose_paths_dropped(self, paths: list[str]):
        """진단은 원래부터 사진 한 장만 다루는 흐름이라(gui/quality_diagnosis_dialog.py),
        여러 장이나 폴더가 떨어지면 무엇을 골라야 할지 추측하지 않고 안내만
        하고 끝낸다."""
        valid = [p for p in paths if Path(p).exists()]
        if len(valid) != 1 or Path(valid[0]).is_dir():
            info_dialog(
                self,
                "진단은 사진 한 장만 가능해요 — 여러 장이나 폴더는 '검사'나 '정리'를 이용해주세요.",
            )
            return
        self._run_diagnose(valid[0])

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

    def _open_diagnose(self):
        """스캔 없이 사진 한 장만 바로 골라서 진단을 실행하는 진입점 —
        gui/quality_diagnosis_dialog.py의 분석/결과 흐름을 그대로 재사용한다."""
        start_dir = self._default_browse_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "진단할 사진 선택", start_dir, IMAGE_FILE_FILTER
        )
        if not path:
            return
        self._remember_browse_dir(str(Path(path).parent))
        self._run_diagnose(path)

    def _run_diagnose(self, path: str) -> None:
        width = height = None
        try:
            from PIL import Image

            with Image.open(path) as img:
                width, height = img.size
        except Exception:
            pass  # 크기를 못 읽어도 예상 소요 시간 안내만 빠질 뿐 기능은 그대로 동작

        run_quality_diagnosis(self, path, width, height)
