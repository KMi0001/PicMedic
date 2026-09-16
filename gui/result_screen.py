"""
gui/result_screen.py

PRD 18장 "Screen 03 — Scan Result" 구현.
"""

from __future__ import annotations

from datetime import datetime
from os.path import commonpath
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QRect, QRectF, QPointF, QSize, QItemSelectionModel, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QFrame,
    QMenu,
    QToolButton,
    QProgressBar,
)

from core.category_finder import CATEGORIES as CATEGORY_FINDER_DEFS
from gui.image_viewer import ImageViewer
from gui.theme import COLORS, STATUS_COLORS, STATUS_DOT
from models.file_info import FileStatus, RecoveryPossibility
from models.scan_result import ScanResult
from utils.file_utils import format_file_size


class _HubCategoryWorker(QThread):
    """정리 카드(동물친구들 등)와 표의 "카테고리" 컬럼을 채우기 위해, 검사
    결과가 나오는 즉시 전체 사진 x 5개 카테고리를 백그라운드에서 계산한다
    (core/category_finder.py::detect_all — 사진당 인코딩 1번 + 카테고리 5개
    비교). 취소 버튼은 없다 — 이 화면 자체는 계속 조작 가능하고(필터/체크박스/
    확장자 변환은 바로 써도 됨) 이 계산은 조용히 뒤에서 끝난다. 세션이
    닫히거나 새 결과로 다시 시작해야 하면 cancel()로 멈춘다.

    2026-09-13: 원래 gui/organize_hub_screen.py(검사 결과와 별도의 "정리 허브"
    화면)에 있던 걸 그대로 옮겨왔다 — 사용자 요청으로 그 화면 자체를 없애고
    검사 결과 화면 하나로 합쳤다."""

    file_classified = Signal(str, list)  # path, list[(category_id, confidence)] (매칭, 0개 이상)
    finished_all = Signal()

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self._files = files
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        from core.category_finder import detect_all

        for info in self._files:
            if self._cancel_requested:
                return
            try:
                results = detect_all(info.path)
            except Exception:
                results = {}
            matched = [(cat_id, result.confidence) for cat_id, result in results.items() if result.matched]
            self.file_classified.emit(info.path, matched)
        self.finished_all.emit()

# "손상" 칩/필터는 완전 손상뿐 아니라 지원되지 않는 형식/이미지가 아닌 파일/분석
# 불가까지 한데 묶는다 — 사용자 요청(2026-09-08): "오류나 지원안함은 손상으로
# 넣자, 어차피 손상정도면 복구 못해주잖아" — 어차피 복구 불가능은 매한가지라
# 필터를 그만큼 잘게 나눌 필요가 없다는 판단.
_CORRUPTED_LIKE_STATUSES = (
    FileStatus.CORRUPTED,
    FileStatus.UNSUPPORTED,
    FileStatus.NOT_AN_IMAGE,
    FileStatus.UNKNOWN,
)


def _corrupted_like_count(result: ScanResult) -> int:
    return sum(1 for f in result.files if f.status in _CORRUPTED_LIKE_STATUSES)


def _outline_icon(color: str, size: int, draw) -> QPixmap:
    """스트로크만 있는 아웃라인 벡터 아이콘 공통 뼈대 (gui/home_screen.py의
    _image_icon_pixmap과 같은 스타일 — 24 기준 좌표에 scale을 곱해서 그린다).
    draw(painter, scale)를 호출해 실제 모양만 그리게 한다."""
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


def _home_icon_pixmap(color: str, size: int = 18) -> QPixmap:
    def draw(painter, scale):
        roof = QPainterPath()
        roof.moveTo(3 * scale, 11 * scale)
        roof.lineTo(12 * scale, 4 * scale)
        roof.lineTo(21 * scale, 11 * scale)
        painter.drawPath(roof)
        painter.drawLine(QPointF(5.5 * scale, 9.5 * scale), QPointF(5.5 * scale, 20 * scale))
        painter.drawLine(QPointF(5.5 * scale, 20 * scale), QPointF(18.5 * scale, 20 * scale))
        painter.drawLine(QPointF(18.5 * scale, 20 * scale), QPointF(18.5 * scale, 9.5 * scale))
        painter.drawRoundedRect(QRectF(10 * scale, 13 * scale, 4 * scale, 7 * scale), 1 * scale, 1 * scale)

    return _outline_icon(color, size, draw)


def _search_icon_pixmap(color: str, size: int = 22) -> QPixmap:
    def draw(painter, scale):
        painter.drawEllipse(QPointF(10.5 * scale, 10.5 * scale), 6.5 * scale, 6.5 * scale)
        painter.drawLine(QPointF(15.2 * scale, 15.2 * scale), QPointF(20 * scale, 20 * scale))

    return _outline_icon(color, size, draw)


def _chevron_icon_pixmap(color: str, direction: str, size: int = 16) -> QPixmap:
    """뷰어 열기/닫기 손잡이용 "<"/">" 화살표. 텍스트 글자로 넣었더니 버튼
    폭(18px)이 전역 QPushButton padding(8px 16px, gui/theme.py)보다 좁아서
    아예 안 보이는 문제가 있었다(2026-09-08, 사용자 리포트) — 아이콘으로 직접
    그려서 패딩과 무관하게 항상 보이게 한다."""

    def draw(painter, scale):
        if direction == "right":
            painter.drawLine(QPointF(9 * scale, 5 * scale), QPointF(15 * scale, 12 * scale))
            painter.drawLine(QPointF(15 * scale, 12 * scale), QPointF(9 * scale, 19 * scale))
        else:
            painter.drawLine(QPointF(15 * scale, 5 * scale), QPointF(9 * scale, 12 * scale))
            painter.drawLine(QPointF(9 * scale, 12 * scale), QPointF(15 * scale, 19 * scale))

    return _outline_icon(color, size, draw)


class CheckAllHeaderView(QHeaderView):
    """체크박스 칼럼(0번) 헤더에 전체선택/해제용 체크박스를 그려 넣는다."""

    toggled = Signal(bool)

    CHECK_COLUMN = 0
    BOX_SIZE = 16

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._checked = False
        self.setSectionsClickable(True)

    def set_checked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.updateSection(self.CHECK_COLUMN)

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != self.CHECK_COLUMN:
            return

        box = self._box_rect(rect)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)

        if self._checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["surface"]))
            painter.drawRoundedRect(box, 4, 4)
            inner = box.adjusted(4, 4, -4, -4)
            painter.setBrush(QColor(COLORS["primary"]))
            painter.drawRoundedRect(inner, 2, 2)
        else:
            painter.setPen(QColor(COLORS["border"]))
            painter.setBrush(QColor(COLORS["surface"]))
            painter.drawRoundedRect(box.adjusted(1, 1, -1, -1), 4, 4)

        painter.restore()

    def _box_rect(self, section_rect) -> QRect:
        size = self.BOX_SIZE
        x = section_rect.x() + (section_rect.width() - size) // 2
        y = section_rect.y() + (section_rect.height() - size) // 2
        return QRect(x, y, size, size)

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self.logicalIndexAt(pos) == self.CHECK_COLUMN:
            self._checked = not self._checked
            self.updateSection(self.CHECK_COLUMN)
            self.toggled.emit(self._checked)
            return
        super().mousePressEvent(event)


class _NumericSortItem(QTableWidgetItem):
    """표시 텍스트(예: '1.5 MB')가 아니라 Qt.UserRole에 저장해둔 실제 값(바이트 수,
    타임스탬프 등) 기준으로 정렬한다. 문자열로 정렬하면 '10 KB'가 '2 KB'보다
    앞에 오는 식으로 잘못 정렬되는 문제를 피한다."""

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            self_key = self.data(Qt.UserRole)
            other_key = other.data(Qt.UserRole)
            if self_key is not None and other_key is not None:
                return self_key < other_key
        return super().__lt__(other)


CHIP_WIDTH = 96  # 라벨 길이(정상~형식 불일치)가 달라도 카드 폭이 들쭉날쭉해지지 않게 고정


class SummaryChip(QFrame):
    """상태별 개수 카드. clickable=True로 만들면 눌러서 clicked 시그널을 낼 수 있다
    (예: gui/recovery_result_screen.py에서 카드를 눌러 해당 파일 목록을 보여줄 때) —
    기본값 False인 화면(검사 결과/복구 화면의 요약 카드)은 지금처럼 그냥 정보 표시용."""

    clicked = Signal()

    def __init__(self, label: str, color: str, parent=None, clickable: bool = False):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(CHIP_WIDTH)
        if clickable:
            self.setProperty("clickable", "true")
            self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.value_label = QLabel("0")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setWordWrap(True)
        self.value_label.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
        self._value_color = color
        name_label = QLabel(label)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(self.value_label)
        layout.addWidget(name_label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_value(self, value: int):
        self.value_label.setText(f"{value:,}")

    def set_selected(self, selected: bool) -> None:
        """이 칩이 지금 활성 필터임을 테두리 강조로 보여준다(카드형 필터 —
        gui/theme.py의 QFrame#Card[selected="true"] 참고). clickable 칩에서만 쓴다."""
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_text(self, text: str):
        """숫자 카운트 대신 자유 텍스트를 보여준다(예: gui/date_organize_screen.py의
        "2023.11 ~ 2025.06" 같은 날짜 범위). 숫자보다 길어서 폭에 못 들어갈 수
        있으니, 폰트를 줄이고 줄바꿈을 허용해서 절대 잘리지 않게 한다(2줄까지
        자연스럽게 늘어남 — 카드 높이가 고정이 아니라 내용에 맞춰 늘어나므로
        레이아웃이 깨지지 않는다)."""
        self.value_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._value_color};")
        self.value_label.setText(text)


def _set_primary_active(button: QPushButton, active: bool) -> None:
    """버튼을 지금 누를 수 있는(active) 상태면 메인 색상(objectName="Primary")
    으로, 아니면 기본 스타일로 보이게 한다 — QSS는 objectName 기반이라
    바뀔 때마다 unpolish/polish로 강제로 다시 그려야 반영된다."""
    button.setObjectName("Primary" if active else "")
    button.style().unpolish(button)
    button.style().polish(button)


class ResultScreen(QWidget):
    file_selected = Signal(object)       # FileInfo
    recovery_requested = Signal(list)    # list[FileInfo] — 확장자 변환/복원
    rescan_requested = Signal()
    resume_requested = Signal()          # 중단된 검사를 나머지 파일부터 이어서 진행

    # 2026-09-13: 검사 결과 화면과 별도였던 "정리 허브"(gui/organize_hub_screen.py)를
    # 없애고 이 화면에 합치면서 추가된 시그널 — 카드를 누르면 각 정리 화면으로 이동.
    duplicates_requested = Signal()
    similar_requested = Signal()
    date_organize_requested = Signal()
    city_organize_requested = Signal()
    category_finder_requested = Signal(str)  # category_id — core/category_finder.py::CATEGORIES 키

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: ScanResult | None = None
        self._current_files: list = []
        self._syncing = False  # 체크박스<->행 선택 동기화 재진입 방지

        # 카테고리 찾기 백그라운드 계산(옛 organize_hub_screen.py에서 이관) 상태.
        self._category_matches: dict[str, list] | None = None  # None=아직 계산 전, 완료되면 cat_id -> [(FileInfo, confidence), ...]
        self._category_by_path: dict[str, list[str]] = {}  # path -> 매칭된 category_id 목록(표시용)
        self._row_by_path: dict[str, int] = {}  # path -> 표 행 번호(카테고리 컬럼 실시간 갱신용)
        self._hub_worker: _HubCategoryWorker | None = None
        self._category_scan_total = 0
        self._category_scan_done = 0
        self.category_finder_cards: dict[str, QFrame] = {}  # _build_card로 채워짐(아래)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_search_icon_pixmap(COLORS["primary"], 26))
        header_row.addWidget(title_icon)
        title = QLabel("검사 결과")
        title.setObjectName("Title")
        header_row.addWidget(title)
        header_row.addStretch(1)
        # "다시 검사"를 눌러도 실제로는 홈 화면(파일/폴더 재선택)으로 돌아갈 뿐이라
        # (gui/main_window.py의 rescan_requested 연결부 참고) 이름과 동작이 어긋났었다.
        # 실제 동작에 맞게 "홈" + 집 아이콘으로 바꾸고, 은은하게 강조되도록 글자/아이콘만
        # primary색을 준다(화면의 진짜 주요 동작인 "Medic!"과 겹치지 않게 배경은 그대로).
        home_btn = QPushButton(" 홈")
        home_btn.setIcon(QIcon(_home_icon_pixmap(COLORS["primary"])))
        home_btn.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 600;")
        home_btn.clicked.connect(self.rescan_requested.emit)
        header_row.addWidget(home_btn)

        outer.addLayout(header_row)

        self.cancelled_banner_frame = QFrame()
        self.cancelled_banner_frame.setStyleSheet(
            f"background-color: {COLORS['surface']}; border: 1px solid {COLORS['warning']}; border-radius: 8px;"
        )
        banner_layout = QHBoxLayout(self.cancelled_banner_frame)
        banner_layout.setContentsMargins(12, 8, 12, 8)

        self.cancelled_banner = QLabel("")
        self.cancelled_banner.setWordWrap(True)
        self.cancelled_banner.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600; border: none;")
        banner_layout.addWidget(self.cancelled_banner, stretch=1)

        self.resume_btn = QPushButton("이어서 검사")
        self.resume_btn.clicked.connect(self.resume_requested.emit)
        banner_layout.addWidget(self.resume_btn)

        self.cancelled_banner_frame.hide()
        outer.addWidget(self.cancelled_banner_frame)

        # 칩 자체가 필터다(2026-09-08, 사용자 요청으로 드롭다운 제거) — 누른 칩이
        # 곧 지금 표에 걸린 필터이고, 선택된 칩은 테두리로 표시된다
        # (SummaryChip.set_selected / _update_chip_selection 참고). "손상" 칩은
        # 완전 손상뿐 아니라 지원안함/이미지아님/분석불가까지 다 포함한다(어차피
        # 복구 불가능은 매한가지라서). "복구 필요"는 기존 "복구 가능한 파일 보기"
        # 버튼을 같은 카드 형식으로 통합한 것.
        chips_row = QHBoxLayout()
        self.chip_total = SummaryChip("총 파일", COLORS["text"], clickable=True)
        self.chip_normal = SummaryChip("정상", STATUS_COLORS["정상"], clickable=True)
        self.chip_mismatch = SummaryChip("형식 불일치", STATUS_COLORS["형식_불일치"], clickable=True)
        self.chip_partial = SummaryChip("부분 손상", STATUS_COLORS["부분_손상"], clickable=True)
        self.chip_corrupted = SummaryChip("손상", STATUS_COLORS["손상"], clickable=True)
        self.chip_recovered = SummaryChip("복구 완료", STATUS_COLORS["복구_완료"], clickable=True)
        self.chip_recovery_needed = SummaryChip("복구 필요", COLORS["warning"], clickable=True)
        self.chip_total.clicked.connect(lambda: self._filter_by_chip("전체"))
        self.chip_normal.clicked.connect(lambda: self._filter_by_chip("정상"))
        self.chip_mismatch.clicked.connect(lambda: self._filter_by_chip("형식 불일치"))
        self.chip_partial.clicked.connect(lambda: self._filter_by_chip("부분 손상"))
        self.chip_corrupted.clicked.connect(lambda: self._filter_by_chip("손상"))
        self.chip_recovered.clicked.connect(lambda: self._filter_by_chip("복구 완료"))
        self.chip_recovery_needed.clicked.connect(lambda: self._filter_by_chip("복구 필요"))
        for chip in (
            self.chip_total,
            self.chip_normal,
            self.chip_mismatch,
            self.chip_partial,
            self.chip_corrupted,
            self.chip_recovered,
            self.chip_recovery_needed,
        ):
            chips_row.addWidget(chip)
        # DESIGN.md "상태 요약 카드" 원칙: 화면이 왼쪽 정렬이면 칩도 왼쪽에 맞추고
        # 뒤쪽에 stretch를 둬서 칩 자체가 늘어나진 않게 한다 — 없으면 큰 창에서
        # 칩들이 왼쪽에 몰리고 나머지 절반이 텅 비어 보인다.
        chips_row.addStretch(1)
        outer.addLayout(chips_row)
        self._active_filter = "전체"
        self._update_chip_selection()

        # 필터 드롭다운은 칩으로 대체돼 없어졌고, 이 줄엔 검사한 폴더 경로(좌)와
        # 검색창(우)만 남는다.
        filter_row = QHBoxLayout()
        # 검사한 폴더 경로 — 한 줄로 보여준다(경로 전체는 툴팁으로도 확인 가능).
        # stretch=1을 안 줬을 때는 QLabel의 word-wrap sizeHint가 실제 필요한
        # 가로 폭보다 좁게 잡혀서, 옆에 남는 공간이 있는데도 줄바꿈되며 잘려
        # 보이는 문제가 있었다(2026-09-08, 사용자 리포트) — 이 줄의 남는 폭을
        # 이 라벨이 먼저 차지하게 해서 한 줄로 다 보이게 한다.
        self.scan_path_label = QLabel("")
        self.scan_path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        filter_row.addWidget(self.scan_path_label, stretch=1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("파일명·확장자·실제 형식 검색")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_box)
        outer.addLayout(filter_row)

        # 2026-09-13: "카테고리" 컬럼 추가 — 옛 정리 허브 화면의 카테고리
        # 찾기(동물친구들 등) 백그라운드 계산 결과를 이 표에서 바로 보여준다.
        # 2026-09-16: "촬영 기기" 컬럼 추가(상세 화면 두 곳에만 있던 걸 목록에도
        # 노출 — "결과 목록에 보이게 하라니깐" 피드백) + "실제 형식" 컬럼 제거
        # (검색으로는 여전히 걸리지만 표에는 더 이상 안 보임, 사용자 요청).
        self.table = QTableWidget(0, 8)
        self._header = CheckAllHeaderView(self.table)
        self._header.toggled.connect(self._on_header_toggled)
        self.table.setHorizontalHeader(self._header)
        self.table.setHorizontalHeaderLabels(
            ["", "상태", "파일명", "확장자", "크기", "수정일", "카테고리", "촬영 기기"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        # 정렬(헤더 클릭)이 일어나면 Qt가 행 순서는 새로 맞춰주지만, setCellWidget로
        # 심어둔 카테고리 배지는 행을 따라오지 않고 원래 위치에 남는 함정이 있다
        # (experiments/organize_hub_redesign_mockup/merged_screen_options.py에서
        # 이미 겪은 문제 — 그 스크립트는 한 번만 그려서 안 드러났을 뿐). 정렬이
        # 바뀔 때마다 배지를 새 행 순서에 맞춰 다시 그린다.
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        # 좌측 접이식 미리보기 패널 — 행을 클릭(선택)만 해도 여기 바로 사진이
        # 보인다. 더 크게/자세히 보려면(EXIF 등) 기존처럼 더블클릭으로 상세
        # 화면을 그대로 연다. 기본은 접혀 있고 목록 경계의 "‹/›" 손잡이로만 편다.
        #
        # QSplitter 대신 고정폭 패널 + 일반 레이아웃을 쓴다 — QSplitter는 보이는
        # 자식의 minimumSizeHint를 계속 창 전체 최소 크기 계산에 반영하는데,
        # 뷰어가 켜진 채로 창 테두리를 드래그하면 이 최소 크기 재계산이 OS의
        # 라이브 리사이즈 루프와 충돌해 창 제목표시줄(최소화/최대화/닫기 버튼)이
        # 잠깐 가려지는 문제가 있었다(2026-09-08, 사용자 리포트) — 폭이 고정된
        # 단순 레이아웃으로 바꿔 그 충돌 소지를 없앴다.
        # 카드 테두리를 일부러 안 준다("틀을 없애고 사진을 중앙에" 요청,
        # 2026-09-08) — 배경색만 있는 평범한 패널 위에 사진이 바로 떠 있는
        # 모양이 되게 한다. 회전/맞추기 버튼도 위쪽 줄 대신 사진 위에 반투명
        # 오버레이로 얹는다(overlay_controls=True, experiments/
        # viewer_redesign_prototype에서 방향 확인).
        self.viewer_panel = QFrame()
        self.viewer_panel.setFixedWidth(320)
        viewer_layout = QVBoxLayout(self.viewer_panel)
        viewer_layout.setContentsMargins(4, 4, 4, 4)
        self.inline_viewer = ImageViewer(
            placeholder_text="파일을 선택하면 미리보기가 표시됩니다.", overlay_controls=True
        )
        viewer_layout.addWidget(self.inline_viewer)
        self.viewer_panel.hide()

        # 목록 경계에 붙는 손잡이 — 접혀있을 땐 ">"(누르면 열림), 펴져있을 땐
        # "<"(누르면 닫힘) 아이콘을 보여준다. 헤더/필터 줄에 있던 별도 텍스트
        # 버튼보다 목록에 바로 붙어있는 게 더 직관적이라는 사용자 피드백으로 옮김.
        # QPushButton 대신 QToolButton을 쓰는 이유: gui/theme.py의 전역
        # QPushButton{padding: 8px 16px} 규칙이 이 좁은 버튼 안 내용을 다
        # 밀어내서 아예 안 보이는 문제가 있었다 — QToolButton은 그 규칙의
        # 대상이 아니라서 자체 스타일만 먹는다.
        self.viewer_handle_btn = QToolButton()
        self.viewer_handle_btn.setIcon(QIcon(_chevron_icon_pixmap(COLORS["text_secondary"], "right")))
        self.viewer_handle_btn.setIconSize(QSize(14, 14))
        self.viewer_handle_btn.setFixedWidth(22)
        self.viewer_handle_btn.setAutoRaise(True)
        self.viewer_handle_btn.setCursor(Qt.PointingHandCursor)
        self.viewer_handle_btn.setToolTip("뷰어 열기")
        self.viewer_handle_btn.setStyleSheet(
            f"QToolButton {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px; }} "
            f"QToolButton:hover {{ border-color: {COLORS['primary']}; }}"
        )
        self.viewer_handle_btn.clicked.connect(self._toggle_viewer)

        content_row = QHBoxLayout()
        content_row.setSpacing(0)
        content_row.addWidget(self.viewer_panel)
        content_row.addWidget(self.viewer_handle_btn)
        content_row.addWidget(self.table, stretch=1)
        outer.addLayout(content_row, stretch=1)

        bottom_row = QHBoxLayout()
        self.selection_label = QLabel("선택된 파일 없음")
        self.selection_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        bottom_row.addWidget(self.selection_label)
        bottom_row.addStretch(1)
        # "Medic!"은 확장자 변환(빠른 파일 I/O)만 계속 배치로 묶는다. 화질
        # 개선/얼굴 복원/디블러/디노이즈/사진 진단은 전부 제거되어(2026-09-13)
        # 지금은 이 버튼 하나만 남았다.
        self.recover_selected_btn = QPushButton("확장자 변환")
        self.recover_selected_btn.setEnabled(False)
        self.recover_selected_btn.clicked.connect(self._on_recover_selected)
        bottom_row.addWidget(self.recover_selected_btn)
        # 처음엔 비활성 상태라 기본(회색) 스타일로 시작 — 선택 상태가 바뀔
        # 때마다 _update_selection_label()이 활성 여부에 맞춰 다시 칠한다.
        _set_primary_active(self.recover_selected_btn, False)
        outer.addLayout(bottom_row)

        # --- 정리 카드 (2026-09-13, 옛 gui/organize_hub_screen.py를 이 화면에 합침) ---
        organize_header = QHBoxLayout()
        organize_label = QLabel("정리")
        organize_label.setStyleSheet("font-weight: 700; font-size: 14px; margin-top: 4px;")
        organize_header.addWidget(organize_label)
        organize_header.addStretch(1)
        # 카테고리 찾기 백그라운드 계산(=사진 x 5개 카테고리 판단, 사진이
        # 많으면 몇 분씩 걸릴 수 있음) 진행 중임을 알려주는 진행률 표시 —
        # 2026-09-16, 사용자 요청("정리중인 파일들이 있으면 프로그레스바로
        # 보여줘"). 모달 팝업이 아니라 이 줄에 붙는 인라인 바다 — 이 화면은
        # 계산 중에도 계속 조작 가능해야 하므로(위 _HubCategoryWorker
        # 독스트링 참고) 화면을 막는 ProgressDialog는 여기 원칙과 안 맞는다.
        self.category_progress_label = QLabel("")
        self.category_progress_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        organize_header.addWidget(self.category_progress_label)
        self.category_progress_bar = QProgressBar()
        self.category_progress_bar.setFixedWidth(160)
        self.category_progress_bar.setFixedHeight(10)
        self.category_progress_bar.setTextVisible(False)
        self.category_progress_bar.hide()
        organize_header.addWidget(self.category_progress_bar)
        outer.addLayout(organize_header)

        self.duplicates_card = self._build_card(
            "중복 파일", "완전히 똑같은 사진을 찾아요.", self.duplicates_requested.emit
        )
        self.similar_card = self._build_card(
            "유사 사진", "리사이즈·재저장으로 약간 다른, 비슷한 사진을 찾아요.", self.similar_requested.emit
        )
        self.date_card = self._build_card(
            "날짜별", "촬영일 기준으로 묶어서 폴더 정리 미리보기를 보여줘요.", self.date_organize_requested.emit
        )
        self.city_card = self._build_card(
            "도시별", "GPS 위치가 있는 사진을 지도에서 도시별로 훑어봐요.", self.city_organize_requested.emit
        )
        for category_id, category in CATEGORY_FINDER_DEFS.items():
            self.category_finder_cards[category_id] = self._build_card(
                category.title,
                category.card_description,
                lambda cid=category_id: self.category_finder_requested.emit(cid),
            )

        cards_grid = QGridLayout()
        cards_grid.setSpacing(10)
        all_cards = [self.duplicates_card, self.similar_card, self.date_card, self.city_card] + list(
            self.category_finder_cards.values()
        )
        for idx, card in enumerate(all_cards):
            cards_grid.addWidget(card, idx // 3, idx % 3)
        outer.addLayout(cards_grid)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # --- 외부에서 호출 --------------------------------------------------

    def set_result(
        self,
        result: ScanResult,
        cancelled: bool = False,
        planned_total: int | None = None,
        remaining_paths: list | None = None,
        scan_paths: list | None = None,
    ):
        self.result = result
        path_text = _format_scan_path(scan_paths or [])
        self.scan_path_label.setText(path_text)
        self.scan_path_label.setToolTip(path_text)
        self.chip_total.set_value(result.total)
        self.chip_normal.set_value(result.normal)
        self.chip_mismatch.set_value(result.mismatch)
        self.chip_partial.set_value(result.partial_corruption)
        self.chip_corrupted.set_value(_corrupted_like_count(result))
        self.chip_recovered.set_value(result.recovered)
        self.chip_recovery_needed.set_value(len(result.recoverable_files()))

        dup_count = len(result.duplicate_groups())
        self._set_card_count(self.duplicates_card, f"{dup_count}그룹" if dup_count else "없음")
        date_count = len(result.date_groups())
        self._set_card_count(self.date_card, f"{date_count}개 묶음" if date_count else "-")
        # 카테고리 찾기 백그라운드 계산도 여기서 같이 시작한다(옛 정리 허브의
        # set_result와 같은 타이밍) — _populate_table보다 먼저 시작해야 아직
        # 계산 전인 셀이 "-"가 아니라 "분석 중"으로 바로 보인다.
        self._start_category_scan()

        if cancelled:
            planned = planned_total or result.total
            self.cancelled_banner.setText(
                f"⚠ 검사가 중단되어 {result.total:,} / {planned:,}개 파일까지만 검사되었습니다."
            )
            self.resume_btn.setVisible(bool(remaining_paths))
            self.cancelled_banner_frame.show()
        else:
            self.cancelled_banner_frame.hide()

        self._active_filter = "전체"
        self.search_box.clear()
        self._apply_filters()

    def refresh_current_result(self):
        """복구/중복·유사 정리 후 파일 상태나 개수가 갱신됐을 때 요약/테이블을
        다시 그린다. 중복/유사 정리는 result.remove()로 total 자체가 줄어들 수
        있어서(복구는 상태만 바뀌고 total은 그대로라 이 chip은 원래 안 건드려도
        됐음) 총 파일 chip도 같이 갱신해야 한다."""
        if self.result:
            self.chip_total.set_value(self.result.total)
            self.chip_normal.set_value(self.result.normal)
            self.chip_mismatch.set_value(self.result.mismatch)
            self.chip_partial.set_value(self.result.partial_corruption)
            self.chip_corrupted.set_value(_corrupted_like_count(self.result))
            self.chip_recovered.set_value(self.result.recovered)
            self.chip_recovery_needed.set_value(len(self.result.recoverable_files()))
            dup_count = len(self.result.duplicate_groups())
            self._set_card_count(self.duplicates_card, f"{dup_count}그룹" if dup_count else "없음")
            date_count = len(self.result.date_groups())
            self._set_card_count(self.date_card, f"{date_count}개 묶음" if date_count else "-")
            self._apply_filters()

    # --- 내부 로직 -----------------------------------------------------

    def _show_recoverable_only(self):
        """gui/scan_session_window.py 등 다른 곳에서 "복구 필요"만 보고 싶을 때
        부르는 이름 그대로 유지 — 실제로는 이제 그 이름의 카드형 칩을 누른 것과
        같다."""
        self._filter_by_chip("복구 필요")

    def _filter_by_chip(self, filter_choice: str):
        self._active_filter = filter_choice
        self._apply_filters()

    def _update_chip_selection(self):
        chips_by_filter = {
            "전체": self.chip_total,
            "정상": self.chip_normal,
            "형식 불일치": self.chip_mismatch,
            "부분 손상": self.chip_partial,
            "손상": self.chip_corrupted,
            "복구 완료": self.chip_recovered,
            "복구 필요": self.chip_recovery_needed,
        }
        for filter_choice, chip in chips_by_filter.items():
            chip.set_selected(filter_choice == self._active_filter)

    def _apply_filters(self):
        if not self.result:
            return

        filter_choice = self._active_filter
        query = self.search_box.text().strip().lower()

        status_map = {
            "정상": FileStatus.NORMAL,
            "형식 불일치": FileStatus.MISMATCH,
            "부분 손상": FileStatus.PARTIAL_CORRUPTION,
            "복구 완료": FileStatus.RECOVERED,
        }

        if filter_choice == "전체":
            files = list(self.result.files)
        elif filter_choice == "복구 필요":
            files = self.result.recoverable_files()
        elif filter_choice == "손상":
            files = [f for f in self.result.files if f.status in _CORRUPTED_LIKE_STATUSES]
        else:
            files = self.result.by_status(status_map[filter_choice])

        self._update_chip_selection()

        if query:
            files = [
                f
                for f in files
                if query in f.filename.lower()
                or query in (f.extension or "").lower()
                or query in (f.detected_format or "").lower()
            ]

        self._current_files = files
        self._populate_table(files)

    def _populate_table(self, files: list):
        # 실사용 버그(15,591장 중 20장으로 필터했다가 다시 "전체"로 돌아오면
        # 응답 없음이 몇 분씩 뜸): self.table.blockSignals(True)는 QTableWidget
        # 자신이 내는 신호(itemChanged 등)만 막지, 테이블이 내부에 따로 들고
        # 있는 QItemSelectionModel의 selectionChanged는 별개 객체라 안 막는다.
        # 필터를 바꾸기 직전에 선택된 행이 있으면, setRowCount()로 행을 지우고
        # 다시 채우는 동안 선택 모델이 selectionChanged를 여러 번(행이 느는
        # 만큼) 쏘고, 그때마다 _on_selection_changed가 자기 나름대로
        # "전체 행을 훑는" O(행 수) 루프를 또 실행해서 — 결과적으로 채우는
        # 동안 O(행 수^2)로 느려졌다(15,591행이면 최악의 경우 수억 번 반복).
        # _set_all_checked()가 이미 쓰던 것과 같은 _syncing 재진입 가드를
        # 여기서도 씌워서, 재구성하는 동안엔 _on_selection_changed가 아무 일도
        # 안 하게 막는다.
        self._syncing = True
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)  # 채우는 동안 정렬되면 행-데이터가 뒤섞일 수 있음
        self.table.setUpdatesEnabled(False)  # 수만 행일 때 매 setItem마다 다시 그리지 않도록
        self._row_by_path = {}
        try:
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            self.table.setRowCount(len(files))
            for row, info in enumerate(files):
                self._row_by_path[info.path] = row
                not_recoverable = info.recoverable == RecoveryPossibility.NOT_RECOVERABLE

                check_item = QTableWidgetItem()
                if not_recoverable:
                    # PRD_MVP우선순위.md '남은 갭 #5': 복구 불가능한(완전 손상) 파일은 애초에
                    # 선택해서 복구를 시도할 수 없게 체크박스 자체를 비활성화한다.
                    check_item.setFlags(Qt.ItemIsUserCheckable)
                    check_item.setToolTip("복구할 수 없는 파일입니다.")
                else:
                    check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Unchecked)
                check_item.setData(Qt.UserRole, info)

                status_value = info.status.value
                dot = STATUS_DOT.get(status_value, "")
                color = STATUS_COLORS.get(status_value, COLORS["text"])

                status_item = QTableWidgetItem(f"{dot} {status_value.replace('_', ' ')}")
                status_item.setForeground(_qcolor(color))

                name_item = QTableWidgetItem(info.filename)
                ext_item = QTableWidgetItem(info.extension)

                size_item = _NumericSortItem(format_file_size(info.file_size))
                size_item.setData(Qt.UserRole, info.file_size)

                mtime = _safe_mtime(info.path)
                date_item = _NumericSortItem(_format_mtime(mtime))
                date_item.setData(Qt.UserRole, mtime if mtime is not None else -1)

                if not_recoverable:
                    for cell in (status_item, name_item, ext_item, size_item, date_item):
                        cell.setToolTip("복구할 수 없는 파일입니다.")

                camera_text = " ".join(part for part in (info.camera_make, info.camera_model) if part)
                camera_item = QTableWidgetItem(camera_text or "-")
                if not_recoverable:
                    camera_item.setToolTip("복구할 수 없는 파일입니다.")

                self.table.setItem(row, 0, check_item)
                self.table.setItem(row, 1, status_item)
                self.table.setItem(row, 2, name_item)
                self.table.setItem(row, 3, ext_item)
                self.table.setItem(row, 4, size_item)
                self.table.setItem(row, 5, date_item)
                self._set_category_cell(row, info.path, not_recoverable)
                self.table.setItem(row, 7, camera_item)

            self.table.blockSignals(False)
        finally:
            self._syncing = False
            self.table.setSortingEnabled(was_sorting)
            self.table.setUpdatesEnabled(True)
        self._update_selection_label()
        self._refresh_inline_viewer()

    def _on_row_double_clicked(self, index):
        if index.column() == 0:
            return  # 체크박스 칸 더블클릭은 상세 화면으로 넘기지 않는다
        item = self.table.item(index.row(), 0)
        if item:
            info = item.data(Qt.UserRole)
            self.file_selected.emit(info)

    def _on_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()

        selected_rows = {r.row() for r in self.table.selectionModel().selectedRows()}
        if row not in selected_rows:
            # 선택되지 않은 행을 우클릭하면 탐색기처럼 그 행 하나만 선택한 것으로
            # 취급한다 — 기존 다중 선택 위에서 우클릭하면 그 선택을 그대로 존중.
            self.table.selectionModel().select(
                self.table.model().index(row, 0),
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
            )

        info = self.table.item(row, 0).data(Qt.UserRole)

        menu = QMenu(self)
        preview_action = menu.addAction("미리보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is preview_action:
            self.file_selected.emit(info)
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _selected_files(self) -> list:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            # 체크박스가 비활성화된(복구 불가능한) 항목은 다른 경로로 체크 상태가
            # 됐더라도 실제 선택 목록에는 절대 포함시키지 않는다 (최종 안전장치).
            if item and item.checkState() == Qt.Checked and (item.flags() & Qt.ItemIsEnabled):
                result.append(item.data(Qt.UserRole))
        return result

    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() != 0 or self._syncing:
            return
        self._syncing = True
        try:
            checked = item.checkState() == Qt.Checked
            row_index = self.table.model().index(item.row(), 0)
            flag = QItemSelectionModel.Select if checked else QItemSelectionModel.Deselect
            self.table.selectionModel().select(row_index, flag | QItemSelectionModel.Rows)
        finally:
            self._syncing = False
        self._update_selection_label()

    def _on_selection_changed(self, *_args):
        if self._syncing:
            return
        self._syncing = True
        # Ctrl+A 등으로 수만 행이 한 번에 선택/해제될 수도 있으므로, 여기도
        # _set_all_checked과 동일하게 다시 그리기/정렬을 잠가둔다.
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        try:
            selected_rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item:
                    want_checked = row in selected_rows and bool(item.flags() & Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked if want_checked else Qt.Unchecked)
            self.table.blockSignals(False)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(was_sorting)
            self._syncing = False
        self._update_selection_label()
        self._refresh_inline_viewer()

    def _on_header_toggled(self, checked: bool):
        self._set_all_checked(Qt.Checked if checked else Qt.Unchecked)

    def _set_all_checked(self, state):
        # 대량(수만 행)일 때 응답 없음이 뜨던 원인 두 가지:
        # 1) 아래서 selectAll()/clearSelection()을 부르면 Qt가 selectionChanged를 쏘고,
        #    그게 _on_selection_changed로 이어져서 방금 이 함수가 한 것과 똑같은
        #    O(행 수) 루프를 또 한 번 돌렸다 (재진입 가드가 이 경로에만 빠져 있었음).
        #    -> _syncing으로 중복 작업을 건너뛰게 함.
        # 2) 정렬이 켜진 채로 17,000번 가까이 setCheckState/selectAll/clearSelection을
        #    부르면 Qt가 매번 재정렬을 검토해서 기하급수적으로 느려짐(실측 6~10초 이상).
        #    -> 이 구간 동안 정렬을 꺼서 0.2초대로 단축됨.
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self._syncing = True
        try:
            self.table.blockSignals(True)
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and (state == Qt.Unchecked or (item.flags() & Qt.ItemIsEnabled)):
                    item.setCheckState(state)
            self.table.blockSignals(False)
            if state == Qt.Checked:
                self.table.selectAll()
            else:
                self.table.clearSelection()
        finally:
            self._syncing = False
            self.table.setUpdatesEnabled(True)
            self.table.setSortingEnabled(was_sorting)
        self._update_selection_label()

    def _update_selection_label(self):
        selected = self._selected_files()
        total_rows = self.table.rowCount()
        if selected:
            self.selection_label.setText(f"{len(selected)}개 파일 선택됨")
        else:
            self.selection_label.setText("선택된 파일 없음")
        can_recover = len(selected) > 0
        self.recover_selected_btn.setEnabled(can_recover)
        _set_primary_active(self.recover_selected_btn, can_recover)

        self._header.set_checked(total_rows > 0 and len(selected) == total_rows)

    def _on_recover_selected(self):
        selected = self._selected_files()
        if selected:
            self.recovery_requested.emit(selected)

    def _toggle_viewer(self):
        showing = not self.viewer_panel.isVisible()
        self.viewer_panel.setVisible(showing)
        direction = "left" if showing else "right"
        self.viewer_handle_btn.setIcon(QIcon(_chevron_icon_pixmap(COLORS["text_secondary"], direction)))
        self.viewer_handle_btn.setToolTip("뷰어 닫기" if showing else "뷰어 열기")
        if showing:
            self._refresh_inline_viewer()

    def _refresh_inline_viewer(self):
        if not self.viewer_panel.isVisible():
            return
        row = self.table.currentRow()
        info = None
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                info = item.data(Qt.UserRole)
        if info is not None:
            self.inline_viewer.set_image_path(info.path)
        else:
            self.inline_viewer.set_pixmap(None)

    # --- 정리 카드 (2026-09-13, 옛 gui/organize_hub_screen.py에서 이관) ------

    def _build_card(self, title: str, description: str, on_click):
        card = QFrame()
        card.setObjectName("Card")
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda event, cb=on_click: cb() if event.button() == Qt.LeftButton else None
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        header = QLabel(title)
        header.setStyleSheet("font-weight: 700; font-size: 13px;")
        header.setAttribute(Qt.WA_TransparentForMouseEvents)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        desc.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_col.addWidget(header)
        text_col.addWidget(desc)
        layout.addLayout(text_col, stretch=1)

        count_label = QLabel("")
        count_label.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 700; font-size: 12px;")
        count_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(count_label)
        card.count_label = count_label

        return card

    def _set_card_count(self, card, text: str | None) -> None:
        if card.count_label is not None:
            card.count_label.setText(text or "")

    def _category_cell_text(self, path: str) -> str:
        # "아직 이 사진 차례가 안 왔다"(분석 중)와 "분석했는데 매칭 카테고리
        # 없음"(-)을 구분해야 한다 — _category_by_path에 키가 있는지로 판단.
        # 뱃지 위젯이 화면엔 보이지만, 이 텍스트는 정렬 기준(가나다순 등)과
        # 검색 대상으로 여전히 필요해서 item에 그대로 심어둔다.
        if path not in self._category_by_path:
            return "분석 중" if self._hub_worker is not None else "-"
        matched_ids = self._category_by_path[path]
        if not matched_ids:
            return "-"
        return ", ".join(CATEGORY_FINDER_DEFS[cat_id].title for cat_id in matched_ids)

    def _build_category_badges(self, matched_ids: list[str]) -> QWidget:
        """카테고리별 색깔 알약(배지) 위젯 — 정리 허브 리디자인 목업
        (experiments/organize_hub_redesign_mockup/mockup.py::build_category_badge)의
        스타일을 그대로 가져왔다. 사진 한 장이 여러 카테고리에 매칭될 수 있어
        배지를 가로로 나란히 놓는다."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        for cat_id in matched_ids:
            category = CATEGORY_FINDER_DEFS[cat_id]
            badge = QLabel(category.title)
            badge.setStyleSheet(
                f"color: white; background-color: {category.color}; border-radius: 8px; "
                f"padding: 1px 7px; font-size: 11px; font-weight: 600;"
            )
            layout.addWidget(badge)
        layout.addStretch(1)
        return container

    def _set_category_cell(self, row: int, path: str, not_recoverable: bool = False) -> None:
        """카테고리 컬럼의 표시 아이템(정렬/검색용 텍스트)과 배지 위젯을 함께
        갱신한다. 초기 채우기(_populate_table), 실시간 분류 결과 도착
        (_on_file_classified), 정렬 후 재동기화(_on_sort_changed) 세 군데가
        모두 이 함수 하나로 모인다 — 세 곳이 각자 따로 하다 어긋나기 쉬운
        코드라 하나로 합침."""
        item = QTableWidgetItem(self._category_cell_text(path))
        if not_recoverable:
            item.setToolTip("복구할 수 없는 파일입니다.")
        self.table.setItem(row, 6, item)

        matched_ids = self._category_by_path.get(path)
        if matched_ids:
            self.table.setCellWidget(row, 6, self._build_category_badges(matched_ids))
        else:
            self.table.removeCellWidget(row, 6)

    def _on_sort_changed(self, *_args) -> None:
        """헤더 클릭으로 행 순서가 바뀌면 Qt가 item은 같이 옮겨주지만, 앞서
        setCellWidget로 심어둔 카테고리 배지는 원래 (행, 열) 위치에 그대로
        남아 텍스트와 배지가 서로 다른 행으로 어긋난다(위 _build_category_badges
        참고) — _row_by_path(카테고리 실시간 갱신용 매핑)도 옛 행 번호를 들고
        있게 되므로 같이 새로 만든다."""
        self._row_by_path = {}
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            info = check_item.data(Qt.UserRole) if check_item is not None else None
            if info is None:
                continue
            self._row_by_path[info.path] = row
            not_recoverable = info.recoverable == RecoveryPossibility.NOT_RECOVERABLE
            self._set_category_cell(row, info.path, not_recoverable)

    def _stop_category_scan(self) -> None:
        if self._hub_worker is not None:
            self._hub_worker.cancel()
            self._hub_worker.wait()
            self._hub_worker = None

    def _start_category_scan(self) -> None:
        """검사가 끝나는 즉시 전체 사진 x 5개 카테고리를 백그라운드에서
        계산해 카드 배지와 표의 "카테고리" 컬럼을 채운다 — 이 화면 자체는
        막지 않으므로 필터/체크박스/확장자 변환은 계산이 끝나기 전에 써도
        그대로 동작한다."""
        self._stop_category_scan()
        self._category_matches = None
        self._category_by_path = {}
        self.category_progress_bar.hide()
        self.category_progress_label.setText("")

        from core.category_finder import is_available

        files = list(self.result.files) if self.result and self.result.files else []
        if not is_available() or not files:
            for card in self.category_finder_cards.values():
                self._set_card_count(card, None)
            return

        self._category_matches = {cat_id: [] for cat_id in CATEGORY_FINDER_DEFS}
        for card in self.category_finder_cards.values():
            self._set_card_count(card, "분석 중")

        readable_files = [info for info in files if info.readable]
        self._category_scan_total = len(readable_files)
        self._category_scan_done = 0
        if self._category_scan_total:
            self.category_progress_bar.setRange(0, self._category_scan_total)
            self.category_progress_bar.setValue(0)
            self.category_progress_bar.show()
            self.category_progress_label.setText(f"카테고리 분석 중 0/{self._category_scan_total}")

        self._hub_worker = _HubCategoryWorker(readable_files, self)
        self._hub_worker.file_classified.connect(self._on_file_classified)
        self._hub_worker.finished_all.connect(self._on_category_scan_finished)
        self._hub_worker.start()

    def _on_file_classified(self, path: str, matched: list) -> None:
        if self._category_matches is None:
            return  # 새 스캔으로 교체된 뒤 도착한 이전 워커의 늦은 신호 — 무시

        self._category_scan_done += 1
        self.category_progress_bar.setValue(self._category_scan_done)
        self.category_progress_label.setText(
            f"카테고리 분석 중 {self._category_scan_done}/{self._category_scan_total}"
        )

        matched_ids = [cat_id for cat_id, _confidence in matched]
        self._category_by_path[path] = matched_ids
        info = next((f for f in self.result.files if f.path == path), None) if self.result else None
        for cat_id, confidence in matched:
            self._category_matches.setdefault(cat_id, [])
            if info is not None:
                self._category_matches[cat_id].append((info, confidence))
            self._set_card_count(
                self.category_finder_cards[cat_id], f"{len(self._category_matches[cat_id])}장"
            )

        row = self._row_by_path.get(path)
        if row is not None:
            self._set_category_cell(row, path)

    def _on_category_scan_finished(self) -> None:
        self._hub_worker = None
        self.category_progress_bar.hide()
        self.category_progress_label.setText("")
        if self._category_matches is not None:
            for matches in self._category_matches.values():
                matches.sort(key=lambda pair: pair[1], reverse=True)  # 확신도 높은 순 — CategoryFinderScreen과 동일
        for cat_id, card in self.category_finder_cards.items():
            count = len(self._category_matches.get(cat_id, [])) if self._category_matches else 0
            self._set_card_count(card, f"{count}장" if count else "없음")

    def category_matches(self, category_id: str) -> list | None:
        """category_id로 매칭된 (FileInfo, confidence) 목록. 백그라운드 계산이
        아직 안 끝났으면 None — 호출하는 쪽(gui/scan_session_category_finder_mixin.py)이
        None이면 기존처럼 CategoryFinderScreen이 직접 계산하도록 폴백한다."""
        if self._category_matches is None or self._hub_worker is not None:
            return None
        return self._category_matches.get(category_id, [])


def _format_scan_path(paths: list) -> str:
    """검사할 때 사용자가 선택한 원본 경로(들)를 화면에 보여줄 문자열로 만든다.
    폴더를 선택했으면 그 폴더 자체를, 파일을 직접 여러 개 골랐으면 그 파일들의
    부모 폴더를 보여준다. 폴더가 여러 개면(예: 폴더 여러 개를 한 번에 선택)
    공통 상위 경로 + "외 N개"로 요약한다."""
    if not paths:
        return ""

    dirs = []
    for p in paths:
        path = Path(p)
        dirs.append(path if path.is_dir() else path.parent)

    unique = list(dict.fromkeys(str(d) for d in dirs))
    if len(unique) == 1:
        return unique[0]

    try:
        common = commonpath(unique)
    except ValueError:
        common = unique[0]
    return f"{common} 외 {len(unique) - 1}개 경로"


def _qcolor(hex_str: str):
    from PySide6.QtGui import QColor

    return QColor(hex_str)


def _safe_mtime(path: str) -> float | None:
    """파일이 스캔 이후 옮겨지거나 삭제됐을 수 있으므로 실패해도 조용히 None을 반환한다."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _format_mtime(mtime: float | None) -> str:
    if mtime is None:
        return "-"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
