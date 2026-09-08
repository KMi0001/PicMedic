"""
gui/organize_hub_screen.py

검사 결과 화면의 "정리" 버튼을 누르면 여는 허브 — 같은 검사 결과를 어떤
렌즈로 볼지 고르는 화면(중복 파일 / 유사 사진 / 날짜별). 헤더에 흩어져
있던 버튼 3개를 여기 하나로 모았다(2026-09-07, 사용자 요청 — "사진을
이렇게도 저렇게도 볼 수 있다"는 개념을 화면으로 분리).

실제 그룹 계산과 화면은 그대로 gui/duplicate_screen.py·similar_screen.py·
date_organize_screen.py가 담당한다 — 이 화면은 진입점만 모아서 보여준다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS
from models.scan_result import ScanResult


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

    def __init__(self, parent=None):
        super().__init__(parent)

        # 화면 전체를 쓰는 큰 창에서 카드 4개짜리 짧은 목록이 창 끝까지 늘어나면
        # 카드마다 오른쪽에 텅 빈 공간만 남아 허전해 보인다 — 내용 폭을 한 번
        # 고정(760px)하고 가운데 정렬해서, 창이 아무리 넓어도 실제 내용은
        # 항상 읽기 좋은 폭으로 모여 있게 한다.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(760)
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

        # 4개를 세로로 쭉 나열하는 대신 2x2 타일로 — 카드 하나가 창 끝까지
        # 늘어나 텅 비어 보이는 것보다, 짧은 설명 문구엔 이 정도 폭이 더 맞는다.
        cards_grid = QGridLayout()
        cards_grid.setSpacing(14)
        cards_grid.addWidget(self.duplicates_card, 0, 0)
        cards_grid.addWidget(self.similar_card, 0, 1)
        cards_grid.addWidget(self.date_card, 1, 0)
        cards_grid.addWidget(self.city_card, 1, 1)
        outer.addLayout(cards_grid)

        outer.addStretch(1)

    def set_result(self, result: ScanResult | None) -> None:
        """카드마다 계산이 가벼운 것만 미리 개수를 보여준다. 유사 사진은
        퍼셉추얼 해시 쌍 비교(O(n^2))라 허브에서 미리 돌리면 느려질 수 있어
        SimilarScreen이 열릴 때 자체 진행률 팝업과 함께 계산하게 그대로
        둔다(개수 배지 없음)."""
        if result is None or not result.files:
            self._set_card_count(self.duplicates_card, None)
            self._set_card_count(self.date_card, None)
            return

        dup_count = len(result.duplicate_groups())
        self._set_card_count(self.duplicates_card, f"{dup_count}그룹" if dup_count else "없음")

        date_count = len(result.date_groups())
        self._set_card_count(self.date_card, f"{date_count}개 묶음" if date_count else "-")

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
