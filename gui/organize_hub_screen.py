"""
gui/organize_hub_screen.py

검사 결과 화면의 "정리" 버튼을 누르면 여는 허브 — 같은 검사 결과를 어떤
렌즈로 볼지 고르는 화면(중복 파일 / 유사 사진 / 날짜별). 헤더에 흩어져
있던 버튼 3개를 여기 하나로 모았다(2026-09-07, 사용자 요청 — "사진을
이렇게도 저렇게도 볼 수 있다"는 개념을 화면으로 분리).

실제 그룹 계산과 화면은 그대로 gui/duplicate_screen.py·similar_screen.py·
date_organize_screen.py가 담당한다 — 이 화면은 진입점만 모아서 보여준다.

2026-09-10, 사용자 요청으로 카드 아래에 "사진 목록" 표 + 미리보기 패널을
추가 — 정리 쪽은 카드(선택지)가 많아서, 어떤 렌즈를 고르기 전에 이번
배치에 뭐가 들어있는지 먼저 훑어볼 수 있게 했다. gui/result_screen.py의
표+ImageViewer 접이식 미리보기 패턴을 그대로 재사용(같은 위젯, 같은 손잡이
아이콘) — 다만 여기는 체크박스/선택 액션이 없는 "훑어보기 전용"이라 목록은
더 단순하다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.image_viewer import ImageViewer
from gui.theme import COLORS
from models.scan_result import ScanResult
from utils.file_utils import format_file_size

THUMB_LIST_MIN_HEIGHT = 220


def _outline_icon(color: str, size: int, draw) -> QPixmap:
    """스트로크만 있는 아웃라인 벡터 아이콘 공통 뼈대 — gui/result_screen.py::
    _outline_icon과 같은 스타일(각 화면이 파일마다 이 패턴을 따로 복붙해서
    씀, 새 abstraction을 안 만드는 게 이 코드베이스 관례)."""
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


def _chevron_icon_pixmap(color: str, direction: str, size: int = 16) -> QPixmap:
    """뷰어 열기/닫기 손잡이 — gui/result_screen.py::_chevron_icon_pixmap과 동일."""

    def draw(p, s):
        if direction == "right":
            p.drawLine(QPointF(9 * s, 5 * s), QPointF(15 * s, 12 * s))
            p.drawLine(QPointF(15 * s, 12 * s), QPointF(9 * s, 19 * s))
        else:
            p.drawLine(QPointF(15 * s, 5 * s), QPointF(9 * s, 12 * s))
            p.drawLine(QPointF(9 * s, 12 * s), QPointF(15 * s, 19 * s))

    return _outline_icon(color, size, draw)


class _CurrentOnlyStack(QStackedWidget):
    """gui/scan_session_window.py::_CurrentOnlyStack와 같은 이유로 필요 —
    기본 QStackedWidget은 모든 페이지 중 가장 큰 사이즈를 최소 크기로 잡아서,
    "아직 진단 전" 안내 문구 한 줄만 보여줄 때도 표+뷰어 페이지만큼의 공간을
    계속 차지해 위아래로 텅 빈 여백이 남는 문제가 있었다(2026-09-10, 실측
    확인)."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class _ClickableCard(QFrame):
    """gui/date_organize_screen.py::_ClickableCard와 같은 패턴 — 카드 전체가
    버튼처럼 동작한다."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.count_label: QLabel | None = None  # _build_card에서 채워짐

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class OrganizeHubScreen(QWidget):
    back_requested = Signal()
    duplicates_requested = Signal()
    similar_requested = Signal()
    date_organize_requested = Signal()
    city_organize_requested = Signal()
    cat_finder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list = []
        # QWidget.isVisible()은 부모 체인 전체가 실제 화면에 떠 있어야 True라
        # (이 화면이 QStackedWidget에서 아직 currentWidget이 되기 전에
        # set_result()가 먼저 불려서) 뷰어를 펼친 채로 둬도 False로 나올 수
        # 있다 — gui/result_screen.py처럼 isVisible()로 펼침 여부를 판단하지
        # 않고 이 플래그로 직접 관리한다.
        self._viewer_expanded = True
        # QStackedWidget에 추가된 뒤 한 번도 안 보인 채로 있다가 처음 current가
        # 될 때, 가운데 정렬(스트레치) 레이아웃이 숨겨진 동안의 낡은 크기로
        # 계산돼서 내용이 왼쪽으로 쏠려 보이는 문제가 있었다(2026-09-10, 사용자
        # 리포트 — "처음 들어가면 왼쪽에 몰려있어, 재진입하면 펴짐"). 첫 표시
        # 때만 한 번 레이아웃을 강제로 다시 계산해서 고친다.
        self._relaid_out_once = False

        # 화면 전체를 쓰는 큰 창에서 카드 목록이 창 끝까지 늘어나면 카드마다
        # 오른쪽에 텅 빈 공간만 남아 허전해 보인다 — 내용 폭을 한 번 고정하고
        # 가운데 정렬해서, 창이 아무리 넓어도 실제 내용은 항상 읽기 좋은
        # 폭으로 모여 있게 한다. 사진 목록 표 + 미리보기 패널이 추가되면서
        # (2026-09-10) 760px로는 표가 너무 좁아져 1080px로 넓혔다.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(1080)
        # QHBoxLayout에서 stretch factor가 0인 위젯은 양옆 addStretch(1)에 밀려
        # 그냥 자기 sizeHint(여기선 카드 grid가 요구하는 최소치)만큼만 차지하고
        # 절대 커지지 않는다 — setMaximumWidth만으론 "커질 수 있는 상한"만
        # 정해질 뿐, 실제로 그 상한까지 커지게 만드는 힘(Expanding 정책 +
        # 양옆 스트레치보다 훨씬 큰 stretch factor)이 없으면 창을 넓혀도 내용이
        # 항상 작게 눌려 보인다(2026-09-08, 사용자 리포트 — "정리 화면이
        # 이상하게 좁다"). 아래 두 줄이 그 힘을 준다.
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(content, 100)
        root.addStretch(1)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("정리")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        hint = QLabel("같은 사진을 여러 방식으로 훑어볼 수 있어요 — 눌러서 확인해보세요.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        # 2026-09-10, 사용자 요청으로 순서를 바꿈 — 사진 목록(+미리보기)을 위에,
        # 정리 방식을 고르는 카드들을 아래로("뭐가 있는지 먼저 보고 나서 고른다").
        list_label = QLabel("사진 목록")
        list_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        outer.addWidget(list_label)

        # 2026-09-10: 카드를 고르기 전엔 아직 스캔을 안 한 상태라 표가
        # 비어있다 — 빈 표 대신 "카드를 고르면 채워진다"는 안내를 보여준다
        # (gui/cat_finder_screen.py의 empty_label과 같은 패턴). QStackedWidget로
        # 페이지를 통째로 바꾸는 이유: setVisible(False)만으로는 표의
        # setMinimumHeight(THUMB_LIST_MIN_HEIGHT)가 숨겨진 채로도 레이아웃
        # 공간을 계속 차지해서 안내문 위아래로 텅 빈 여백이 남는 문제가 있었다.
        self.list_empty_label = QLabel(
            "아직 진단 전이에요 — 아래 카드를 고르면 진단이 끝난 뒤 사진 목록이 여기 나와요."
        )
        self.list_empty_label.setWordWrap(True)
        self.list_empty_label.setAlignment(Qt.AlignCenter)
        self.list_empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일명", "폴더", "크기"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(THUMB_LIST_MIN_HEIGHT)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # gui/result_screen.py와 같은 접이식 미리보기 패턴 — 다만 여기는
        # "먼저 훑어보기"가 목적이라 기본값을 펼침으로 둔다(그쪽은 기본 접힘).
        self.viewer_panel = QFrame()
        self.viewer_panel.setFixedWidth(320)
        viewer_layout = QVBoxLayout(self.viewer_panel)
        viewer_layout.setContentsMargins(4, 4, 4, 4)
        self.inline_viewer = ImageViewer(
            placeholder_text="사진을 선택하면 미리보기가 표시됩니다.", overlay_controls=True
        )
        viewer_layout.addWidget(self.inline_viewer)

        self.viewer_handle_btn = QToolButton()
        self.viewer_handle_btn.setIcon(QIcon(_chevron_icon_pixmap(COLORS["text_secondary"], "left")))
        self.viewer_handle_btn.setIconSize(QSize(14, 14))
        self.viewer_handle_btn.setFixedWidth(22)
        self.viewer_handle_btn.setAutoRaise(True)
        self.viewer_handle_btn.setCursor(Qt.PointingHandCursor)
        self.viewer_handle_btn.setToolTip("뷰어 닫기")
        self.viewer_handle_btn.setStyleSheet(
            f"QToolButton {{ background-color: {COLORS['surface']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px; padding: 2px; }} "
            f"QToolButton:hover {{ border-color: {COLORS['primary']}; }}"
        )
        self.viewer_handle_btn.clicked.connect(self._toggle_viewer)

        self.list_content = QWidget()
        list_row = QHBoxLayout(self.list_content)
        list_row.setContentsMargins(0, 0, 0, 0)
        list_row.setSpacing(0)
        list_row.addWidget(self.viewer_panel)
        list_row.addWidget(self.viewer_handle_btn)
        list_row.addWidget(self.table, stretch=1)

        self.list_stack = _CurrentOnlyStack()
        self.list_stack.addWidget(self.list_empty_label)
        self.list_stack.addWidget(self.list_content)
        outer.addWidget(self.list_stack, stretch=1)

        self.duplicates_card = self._build_card(
            "중복 파일", "완전히 똑같은 사진을 찾아요.", self.duplicates_requested
        )
        self.similar_card = self._build_card(
            "유사 사진", "리사이즈·재저장으로 약간 다른, 비슷한 사진을 찾아요.", self.similar_requested
        )
        self.date_card = self._build_card(
            "날짜별", "촬영일 기준으로 묶어서 폴더 정리 미리보기를 보여줘요.", self.date_organize_requested
        )
        self.city_card = self._build_card(
            "도시별", "GPS 위치가 있는 사진을 지도에서 도시별로 훑어봐요.", self.city_organize_requested
        )
        self.cat_finder_card = self._build_card(
            "고양이 찾기",
            "AI로 고양이가 나온 사진을 찾아 모아 보여줘요. (찾는 시간이 필요해요~)",
            self.cat_finder_requested,
        )

        # 세로로 쭉 나열하는 대신 3열 타일로(2026-09-10, 폭이 1080으로 넓어지며
        # 2열보다 3열이 더 꽉 차 보임) — 카드 하나가 창 끝까지 늘어나 텅 비어
        # 보이는 것보다, 짧은 설명 문구엔 이 정도 폭이 더 맞는다.
        cards_grid = QGridLayout()
        cards_grid.setSpacing(14)
        cards_grid.addWidget(self.duplicates_card, 0, 0)
        cards_grid.addWidget(self.similar_card, 0, 1)
        cards_grid.addWidget(self.date_card, 0, 2)
        cards_grid.addWidget(self.city_card, 1, 0)
        cards_grid.addWidget(self.cat_finder_card, 1, 1)
        outer.addLayout(cards_grid)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._relaid_out_once:
            self._relaid_out_once = True
            # 지금 바로 activate()하면 아직 QStackedWidget이 이 위젯에 최종
            # geometry를 넘기기 전일 수 있어(같은 이벤트 처리 중) 한 틱 미룬다.
            QTimer.singleShot(0, self._force_relayout)

    def _force_relayout(self) -> None:
        for layout in self.findChildren(QLayout):
            layout.invalidate()
        self.layout().activate()

    def set_result(self, result: ScanResult | None) -> None:
        """카드마다 계산이 가벼운 것만 미리 개수를 보여준다. 유사 사진은
        퍼셉추얼 해시 쌍 비교(O(n^2))라 허브에서 미리 돌리면 느려질 수 있어
        SimilarScreen이 열릴 때 자체 진행률 팝업과 함께 계산하게 그대로
        둔다(개수 배지 없음)."""
        self._files = list(result.files) if result and result.files else []
        self._populate_table()

        if result is None or not result.files:
            self._set_card_count(self.duplicates_card, None)
            self._set_card_count(self.date_card, None)
            return

        dup_count = len(result.duplicate_groups())
        self._set_card_count(self.duplicates_card, f"{dup_count}그룹" if dup_count else "없음")

        date_count = len(result.date_groups())
        self._set_card_count(self.date_card, f"{date_count}개 묶음" if date_count else "-")

    def _populate_table(self) -> None:
        has_any = bool(self._files)
        self.list_stack.setCurrentWidget(self.list_content if has_any else self.list_empty_label)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._files))
        for row, info in enumerate(self._files):
            name_item = QTableWidgetItem(info.filename)
            name_item.setData(Qt.UserRole, info)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(Path(info.path).parent)))
            size_item = QTableWidgetItem(format_file_size(info.file_size))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, size_item)
        self.table.setSortingEnabled(True)
        if self._files:
            # 뷰어 기본값이 펼침이라(위 __init__ 참고) 처음부터 뭔가 보이게
            # 첫 행을 미리 선택해둔다 — selectRow가 selectionChanged를 쏴서
            # _refresh_inline_viewer()까지 이어진다.
            self.table.selectRow(0)
        else:
            self._refresh_inline_viewer()

    def _on_selection_changed(self, *_args) -> None:
        self._refresh_inline_viewer()

    def _toggle_viewer(self) -> None:
        self._viewer_expanded = not self._viewer_expanded
        self.viewer_panel.setVisible(self._viewer_expanded)
        direction = "left" if self._viewer_expanded else "right"
        self.viewer_handle_btn.setIcon(QIcon(_chevron_icon_pixmap(COLORS["text_secondary"], direction)))
        self.viewer_handle_btn.setToolTip("뷰어 닫기" if self._viewer_expanded else "뷰어 열기")
        if self._viewer_expanded:
            self._refresh_inline_viewer()

    def _refresh_inline_viewer(self) -> None:
        if not self._viewer_expanded:
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

    def _build_card(self, title: str, description: str, signal) -> _ClickableCard:
        card = _ClickableCard()
        card.clicked.connect(signal.emit)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        header = QLabel(title)
        header.setStyleSheet("font-weight: 700; font-size: 14px;")
        header.setAttribute(Qt.WA_TransparentForMouseEvents)
        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        desc.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_col.addWidget(header)
        text_col.addWidget(desc)
        layout.addLayout(text_col, stretch=1)

        count_label = QLabel("")
        count_label.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 700; font-size: 13px;")
        count_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(count_label)
        card.count_label = count_label

        chevron = QLabel("›")
        chevron.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 18px;")
        chevron.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(chevron)

        return card

    def _set_card_count(self, card: _ClickableCard, text: str | None) -> None:
        if card.count_label is not None:
            card.count_label.setText(text or "")
