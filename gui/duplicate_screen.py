"""
gui/duplicate_screen.py

Phase 2 "사진 정리" 1차 범위 — 정확 중복(파일 내용 SHA-256) 탐지 결과를 보여주고,
남길 파일을 고르면 나머지를 임시 휴지통으로 옮긴다(완전 삭제 아님 — utils/trash.py
참고, "원본 보호" 원칙과 절충). PHASE2_사진정리_기획.md 참고. 다시 스캔하지 않고,
같은 검사 세션에서 이미 계산된 FileInfo.content_hash로 ScanResult.duplicate_groups()
를 호출해 그룹만 보여준다.

중복 그룹이 수백 개면 그룹마다 하나씩 고르는 게 비현실적이라(실사용 리포트:
680개 그룹, 이후 재정리 버그로 795개 사례), "폴더째로 중복"인 흔한 경우를
자동으로 묶어서 처리하고, 그래도 카드 하나씩 남는 경우는 다시 신뢰도로 나눈다:
- 그룹 안 파일들이 전부 서로 다른 폴더에 있으면 -> 그 폴더 조합(frozenset)별로
  같은 패턴의 그룹들을 한데 묶고, "이 폴더 남기기"를 한 번만 고르면 그 조합에
  속한 모든 그룹에 일괄 적용된다.
- 그룹 안에 같은 폴더 파일이 2개 이상이면(폴더만으로는 구분 불가) 중 —
  core/duplicate_resolver.py::suggest_keep()이 확신을 가진(파일명 패턴/생성일)
  그룹은 카드 대신 체크박스 표 한 줄로 압축한다("자동 추천" 표, 헤더 체크박스로
  전체 선택/해제, 행 단위 개별 제외도 가능) — a.jpg/a_1.jpg/a_2.jpg류 재정리
  버그가 수백 그룹으로 한꺼번에 생겨도 표 하나로 스크롤만 하면 되게 하기 위함
  (gui/result_screen.py의 CheckAllHeaderView 체크박스 테이블 패턴 재사용, 이미
  수천 행에서 성능 검증됨).
- 그것도 못 정하면(확신 없음, 보통 소수) -> 기존처럼 파일 하나하나 라디오로
  고르게 한다(개별 확인 필요).

모든 조합/그룹/표 행에는 "정리하지 않음"(건너뛰기) 선택지도 있고 기본값이다
(단, 자동 추천 표는 이미 추천이 확실하다는 뜻이라 기본값이 "선택됨"이다 —
기존에도 카드 하나였을 때 추천이 있으면 기본 선택이었던 것과 같은 원칙).
아무것도 안 고르면 그 파일들은 그대로 둔다. 정리를 실행하면 실제로 처리된
(건너뛰지 않은) 카드/행만 화면에서 사라지고, 건너뛴 카드/행은 나중에 다시
볼 수 있게 그대로 남는다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QToolButton,
)

from core.duplicate_resolver import explain_file, suggest_keep, suggest_keep_folder
from gui.common_dialogs import confirm_dialog, info_dialog, ProgressDialog
from gui.result_screen import CheckAllHeaderView, SummaryChip
from gui.theme import COLORS
from gui.trash_worker import TrashMoveWorker
from utils.file_utils import format_file_size

SKIP_LABEL = "이 조합은 정리하지 않음(건너뛰기)"


class _CurrentOnlyStack(QStackedWidget):
    """gui/organize_hub_screen.py::_CurrentOnlyStack와 같은 이유로 필요 — 기본
    QStackedWidget은 숨겨진 페이지도 sizeHint에 반영해서, empty_label만 보여줄
    때도 scroll_area(stretch=1)가 있던 자리만큼 빈 공간을 남긴다. 게다가
    setVisible()만으로 감추면(예전 방식) wordWrap 라벨이 그 남는 공간을 예측
    불가능하게 늘어나 먹어버리는 문제까지 있었다(2026-09-10, 사용자 리포트 —
    "카드형태 버튼이 세로로 늘어나는 현상", 실측: empty_label이 184px로 부풀며
    위치도 아래로 밀림). setCurrentWidget()으로 완전히 바꿔치기해야 둘 다 해결된다."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class _ClickableLabel(QLabel):
    """파일 경로 레이블 — 눌러서 사진을 볼 수 있다는 걸 알 수 있게 커서만 바꾸고,
    클릭 시 clicked를 쏜다(어떤 파일인지는 호출부가 알고 있으므로 인자 없음)."""

    clicked = Signal()

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


def _duplicate_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 겹친 사각형 두 개로 "복사본이 있다"는 의미.
    검사 결과 화면의 돋보기 아이콘과 같은 아웃라인 스트로크 스타일."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    painter.drawRoundedRect(r(3, 6, 13, 13), 2 * scale, 2 * scale)
    painter.drawRoundedRect(r(8, 1, 13, 13), 2 * scale, 2 * scale)

    painter.end()
    return pixmap


def _cluster_by_folder(groups: list[list]) -> tuple[dict[frozenset, list[list]], list[list]]:
    """중복 그룹을 "관련된 폴더 조합"별로 묶는다.

    그룹 안의 모든 파일이 서로 다른 폴더에 있으면(같은 폴더에 2개 이상 없으면)
    폴더 하나를 고르는 것만으로 그 그룹을 해결할 수 있다 — 이런 그룹만 폴더
    조합(frozenset[Path])별로 묶어서 반환한다. 그룹 안에 같은 폴더 파일이
    2개 이상이면(폴더만으로 어떤 걸 남길지 못 정함) manual 목록으로 뺀다.
    """
    clusters: dict[frozenset, list[list]] = {}
    manual: list[list] = []
    for group in groups:
        folders = [Path(info.path).parent for info in group]
        if len(set(folders)) != len(group):
            manual.append(group)
            continue
        key = frozenset(folders)
        clusters.setdefault(key, []).append(group)
    return clusters, manual


class _ClusterEntry:
    """폴더 단위로 일괄 처리 가능한 조합 카드 하나의 상태."""

    __slots__ = ("card", "group_list", "folder_options", "radios", "skip_radio", "suggested_folder")

    def __init__(self, card, group_list, folder_options, radios, skip_radio, suggested_folder=None):
        self.card = card
        self.group_list = group_list
        self.folder_options = folder_options
        self.radios = radios
        self.skip_radio = skip_radio
        self.suggested_folder = suggested_folder  # (Path, 사유) | None — core/duplicate_resolver.py 추천

    @property
    def group_count(self) -> int:
        return len(self.group_list)


class _ManualEntry:
    """폴더만으로는 못 정하는(같은 폴더 안 중복) 그룹 카드 하나의 상태."""

    __slots__ = ("card", "group", "radios", "skip_radio", "suggested_keep")

    def __init__(self, card, group, radios, skip_radio, suggested_keep=None):
        self.card = card
        self.group = group
        self.radios = radios
        self.skip_radio = skip_radio
        self.suggested_keep = suggested_keep  # (FileInfo, 사유) | None — core/duplicate_resolver.py 추천


class DuplicateScreen(QWidget):
    """검사 결과 화면(gui/result_screen.py)의 "중복 파일 보기" 버튼으로 들어오는
    화면. 같은 스캔 세션(gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    # 정리(휴지통 이동) 완료 후 휴지통 화면으로 이동 — 이번에 옮긴 FileInfo 목록을
    # 같이 넘긴다(임시휴지통이 폴더마다 따로 생기므로, 호출부가 이 목록에서
    # "이번에 실제로 쓰인 임시휴지통들"을 계산해서 화면에 알려줘야 함).
    view_trash_requested = Signal(list)
    # 파일 클릭/미리보기 -> 상세보기(FileInfo, 그 파일이 속한 그룹 — 상세
    # 화면에서 방향키로 같은 그룹의 다음/이전 사진을 넘나들 때 씀, 2026-09-08).
    file_selected = Signal(object, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None  # 정리(휴지통 이동) 후 옮긴 파일을 여기서도 빼야 재조회 시 다시 안 나타남
        self._cluster_entries: list[_ClusterEntry] = []
        # (group, keep_info, reason) 병렬 목록. self._auto_parent_rows[i]는
        # self._auto_rows[i]에 해당하는 표의 실제 부모 행 번호 — "삭제될 파일"을
        # 엑셀 행 그룹화처럼 부모 행 바로 아래 숨은 하위 행으로 펼치면서
        # (2026-09-08) 더 이상 인덱스와 행 번호가 같지 않아졌다.
        self._auto_rows: list[tuple[list, object, str]] = []
        self._auto_parent_rows: list[int] = []
        self._auto_table: QTableWidget | None = None
        self._manual_entries: list[_ManualEntry] = []
        self._cluster_section: QLabel | None = None
        self._auto_section: QLabel | None = None
        self._manual_section: QLabel | None = None

        # "정리 실행"으로 파일을 옮기는 동안(수백 개면 눈에 띄게 걸림) UI가 멈춘
        # 것처럼 보이지 않게 gui/trash_worker.py::TrashMoveWorker로 백그라운드
        # 처리한다(gui/recovery_screen.py::RecoveryWorker와 같은 이유).
        self.progress_dialog = ProgressDialog(self)
        self.progress_dialog.cancel_requested.connect(self._on_cleanup_cancel_requested)
        self._worker: TrashMoveWorker | None = None
        # 워커가 끝난 뒤(_on_cleanup_finished) "이 카드/행을 지워도 되는지"
        # 판단하려면 to_process의 각 항목이 어느 카드/행에서 왔는지 알아야 한다 —
        # ("cluster", _ClusterEntry) | ("auto", row_index) | ("manual", _ManualEntry)
        self._pending_entry_refs: list[tuple[str, object]] | None = None

        # 화면 전체를 쓰는 큰 창에서 카드/표가 창 끝까지 늘어나면 오른쪽에 텅 빈
        # 공간이 남아 허전해 보인다(gui/organize_hub_screen.py에서 고친 것과 같은
        # 문제) — 내용 폭을 한 번 고정(900px)하고 가운데 정렬한다. 그룹 병합/추천
        # 로직은 전혀 안 건드리고 바깥 컨테이너만 바꾼 것.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(900)
        # stretch factor 0인 위젯은 양옆 addStretch(1)에 밀려 sizeHint(라디오
        # 버튼 라벨처럼 줄바꿈 안 되는 요소가 정하는 좁은 값)만큼만 차지하고
        # 절대 안 커진다 — setMaximumWidth는 상한만 정할 뿐, 실제로 그 상한
        # 까지 채우는 힘은 Expanding 정책 + 양옆보다 훨씬 큰 stretch factor가
        # 있어야 생긴다(2026-09-08, 사용자 리포트 — "정리 화면이 이상하게
        # 좁다", 실측: 900 의도 → 571만 사용).
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(content, 100)
        root.addStretch(1)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_duplicate_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("중복 사진")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.group_chip = SummaryChip("중복 그룹", COLORS["warning"])
        self.file_chip = SummaryChip("중복 파일", COLORS["warning"])
        self.cluster_chip = SummaryChip("폴더 조합", COLORS["primary"])
        chips_row.addWidget(self.group_chip)
        chips_row.addWidget(self.file_chip)
        chips_row.addWidget(self.cluster_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "폴더째로 겹치는 경우는 폴더 하나만 골라도 관련된 그룹 전부에 적용돼요. "
            "같은 폴더 안 중복 중 확신 가능한 건 표에서 체크박스로 한 번에 처리하고, "
            "애매한 것만 파일을 하나씩 골라주세요. "
            "정리하고 싶지 않은 조합/그룹/행은 \"건너뛰기\"(또는 체크 해제)를 그대로 두면 손대지 않아요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel("중복된 파일이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        # 카드는 항상 컨테이너 폭에 맞춰지므로 가로 스크롤은 필요 없다 — 세로
        # 스크롤바가 나타나며 뷰포트 폭이 살짝 줄어드는 순간(피드백 루프)
        # 불필요한 가로 스크롤바까지 같이 뜨는 문제가 있었다(2026-09-08,
        # 사용자 리포트 — gui/date_group_detail_screen.py에는 이미 적용돼있던
        # 설정이 여기엔 빠져있었음).
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll_area.setWidget(self._list_container)

        self.list_stack = _CurrentOnlyStack()
        self.list_stack.addWidget(self.empty_label)
        self.list_stack.addWidget(self.scroll_area)
        outer.addWidget(self.list_stack, stretch=1)

        # "선택한 파일"이라고 하면 체크/라디오로 고른(=남길) 파일이 옮겨진다는
        # 뜻으로 오해하기 쉽다(gui/similar_screen.py와 같은 문제,
        # 2026-09-09, 사용자 리포트 — "반대 아니야?") — 이 화면은 섹션마다
        # "선택"의 의미가 달라서(자동 추천 표는 체크=적용, 폴더/개별 카드는
        # 라디오=남길 대상) 아예 "선택한"이라는 말을 빼고 실행 자체로 문구를 쓴다.
        self.cleanup_btn = QPushButton("정리 실행 — 임시 휴지통으로 이동")
        self.cleanup_btn.setObjectName("Danger")
        self.cleanup_btn.clicked.connect(self._on_cleanup_clicked)
        outer.addWidget(self.cleanup_btn)

    def set_result(self, result) -> None:
        """검사 결과가 바뀔 때(재검사 등) 호출 — result.duplicate_groups()로
        중복 그룹을 다시 계산해서 보여준다. 그룹이 수백 개면 카드도 그만큼
        만들어야 해서(실사용 리포트: 680개), 만드는 동안 매번 다시 그리지
        않도록 업데이트를 잠깐 꺼둔다 — 안 그러면 위젯 하나 추가할 때마다
        레이아웃을 다시 계산해서 눈에 띄게(때로는 "응답 없음"까지) 느려진다."""
        self._result = result
        groups = result.duplicate_groups() if result else []
        self._cluster_entries = []
        self._auto_rows = []
        self._auto_table = None
        self._manual_entries = []

        self.setUpdatesEnabled(False)
        try:
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            clusters, manual = _cluster_by_folder(groups)

            # 폴더만으로 못 정한 그룹(manual)을 다시 "확신 가능(자동 추천 표)"과
            # "확신 불가(개별 카드)"로 나눈다 — suggest_keep()은 신뢰도 낮으면
            # 이미 None을 반환하도록 설계돼 있어서, 여기서 추가 판단 없이 그
            # 결과를 그대로 신뢰해도 기존 원칙과 어긋나지 않는다.
            auto_rows: list[tuple[list, object, str]] = []
            plain_manual: list[list] = []
            for group in manual:
                suggestion = suggest_keep(group)
                if suggestion is not None:
                    keep_info, reason = suggestion
                    auto_rows.append((group, keep_info, reason))
                else:
                    plain_manual.append(group)

            # 개별로 확인이 필요한(신뢰도 낮은, 보통 소수) 카드를 맨 위에 둔다 —
            # 중복이 많으면(실사용: 수백~수천 그룹) 일괄 처리 가능한 표/카드가
            # 훨씬 길어서, 개별 확인 카드가 밑에 있으면 스크롤하다 놓치기 쉽다는
            # 피드백을 반영했다. 일괄 처리 가능한 두 섹션(폴더 단위/자동 추천)은
            # 그 아래로 옮김 — 이미 정답이 골라져 있어 스크롤로 지나쳐도
            # "정리 실행" 한 번이면 알아서 처리되니 순서가 밀려도 문제없다.
            row = 0
            self._manual_section = QLabel()
            self._manual_section.setStyleSheet("font-weight: 700;")
            self._list_layout.insertWidget(row, self._manual_section)
            row += 1
            for idx, group in enumerate(plain_manual, start=1):
                card, radios, skip_radio, suggested_keep = self._build_group_card(idx, group)
                self._manual_entries.append(_ManualEntry(card, group, radios, skip_radio, suggested_keep))
                self._list_layout.insertWidget(row, card)
                row += 1

            self._cluster_section = QLabel()
            self._cluster_section.setStyleSheet("font-weight: 700; margin-top: 8px;")
            self._list_layout.insertWidget(row, self._cluster_section)
            row += 1
            # 그룹을 많이 해결해주는 조합을 위로
            for key in sorted(clusters, key=lambda k: len(clusters[k]), reverse=True):
                group_list = clusters[key]
                table, folder_options, radios, skip_radio, suggested_folder = self._build_cluster_table(
                    sorted(key), group_list
                )
                self._cluster_entries.append(
                    _ClusterEntry(table, group_list, folder_options, radios, skip_radio, suggested_folder)
                )
                self._list_layout.insertWidget(row, table)
                row += 1

            self._auto_section = QLabel()
            self._auto_section.setStyleSheet("font-weight: 700; margin-top: 8px;")
            self._list_layout.insertWidget(row, self._auto_section)
            row += 1
            self._auto_rows = auto_rows
            self._auto_table = self._build_auto_table(auto_rows)
            self._list_layout.insertWidget(row, self._auto_table)
            row += 1

            self._refresh_summary()
        finally:
            self.setUpdatesEnabled(True)

    def has_pending(self) -> bool:
        """정리할 그룹/조합/행이 아직 남아있는지 — 임시 휴지통에서 뒤로 나올 때
        빈 화면을 거치지 않고 검사 결과로 바로 보낼지 판단하는 데 쓰인다."""
        return bool(self._cluster_entries or self._auto_rows or self._manual_entries)

    def _refresh_summary(self) -> None:
        """칩/빈 상태/섹션 제목을 지금 남아있는 카드/행(_cluster_entries/_auto_rows/
        _manual_entries) 기준으로 다시 계산한다 — 정리 실행 후 일부(건너뛴 것)만
        남을 때도 이걸로 섹션 제목의 개수 표시가 같이 갱신되게 한다."""
        group_count = (
            sum(e.group_count for e in self._cluster_entries)
            + len(self._auto_rows)
            + len(self._manual_entries)
        )
        file_count = (
            sum(len(g) for e in self._cluster_entries for g in e.group_list)
            + sum(len(group) for group, _, _ in self._auto_rows)
            + sum(len(e.group) for e in self._manual_entries)
        )
        has_any = bool(self._cluster_entries or self._auto_rows or self._manual_entries)

        self.group_chip.set_value(group_count)
        self.file_chip.set_value(file_count)
        self.cluster_chip.set_value(len(self._cluster_entries))
        self.list_stack.setCurrentWidget(self.scroll_area if has_any else self.empty_label)
        self.cleanup_btn.setEnabled(has_any)

        self._cluster_section.setVisible(bool(self._cluster_entries))
        if self._cluster_entries:
            self._cluster_section.setText(f"폴더 단위로 정리 가능 · {len(self._cluster_entries)}개 조합")

        self._auto_section.setVisible(bool(self._auto_rows))
        if self._auto_rows:
            self._auto_section.setText(f"자동 추천으로 일괄 정리 가능 · {len(self._auto_rows)}개 그룹")
        if self._auto_table:
            self._auto_table.setVisible(bool(self._auto_rows))

        self._manual_section.setVisible(bool(self._manual_entries))
        if self._manual_entries:
            self._manual_section.setText(
                f"개별로 확인 필요 · {len(self._manual_entries)}개 그룹 (추천 확신 없음)"
            )

    def _build_cluster_table(
        self, folders: list[Path], group_list: list[list]
    ) -> tuple[QTableWidget, list[Path], list[QRadioButton], QRadioButton, tuple[Path, str] | None]:
        """"폴더 단위로 정리 가능" 조합 하나를 표로 보여준다 — 자동 추천
        표와 같은 "체크옵션 / 파일명(로컬주소) / 구분 / 사유" 4칸으로
        통일했다(2026-09-08, 사용자 요청 — 카드마다 모양이 달라 헷갈린다는
        피드백, experiments/cluster_grouping_prototype에서 검증받음). 폴더
        후보마다 라디오 행 하나씩("건너뛰기"도 라디오 행)이고, 후보 행의
        "파일명(로컬주소)" 칸 자체를 누르면(별도 버튼 없이) 그 폴더를
        남겼을 때 그룹마다 정확히 어떤 파일이 지워지는지 바로 아래 펼쳐진다
        (gui/duplicate_screen.py::_build_auto_table과 같은 엑셀 행 그룹화
        방식)."""
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["", "파일명 (로컬주소)", "구분", "사유"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        table.setColumnWidth(0, 32)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setColumnWidth(2, 60)
        table.setColumnWidth(3, 260)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # col1이 Stretch라 표 자체는 가로 스크롤이 필요 없다 — 없으면 표
        # 위젯이 실제 창 폭보다 좁게 배치될 때 "사유" 칸이 표 자체의 가로
        # 스크롤 뒤로 밀려 숨어버릴 수 있다(2026-09-08, 사용자 리포트 —
        # "사유가 안 보인다"의 진짜 원인 — 바깥 QScrollArea만 막아뒀지 표
        # 자신의 가로 스크롤은 안 막아뒀었음).
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setFocusPolicy(Qt.NoFocus)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table: self._on_cluster_context_menu(t, pos))
        table.doubleClicked.connect(lambda index, t=table: self._on_cluster_row_double_clicked(t, index))

        button_group = QButtonGroup(table)
        summary_text = f"폴더 {len(folders)}개 조합 · {len(group_list)}개 그룹에 적용"

        row = 0
        table.insertRow(row)
        skip_radio = QRadioButton()
        skip_radio.setToolTip(summary_text)
        button_group.addButton(skip_radio)
        table.setCellWidget(row, 0, skip_radio)
        skip_item = QTableWidgetItem(SKIP_LABEL)
        skip_item.setToolTip(summary_text)
        table.setItem(row, 1, skip_item)
        # 폴더명 클릭이 라디오를 안 바꾸던 버그(위 folders 루프 참고)를 고치는
        # 김에, "건너뛰기" 칸 클릭도 같은 이유로 라디오를 선택하게 한다 —
        # 위젯이 아니라 QTableWidgetItem이라 클릭이 cellClicked로 온다.
        skip_row = row
        table.cellClicked.connect(
            lambda r, c, skip_row=skip_row, skip_radio=skip_radio: skip_radio.setChecked(True)
            if r == skip_row and c == 1
            else None
        )
        for c in (2, 3):
            dash_item = QTableWidgetItem("-")
            dash_item.setFlags(Qt.NoItemFlags)
            table.setItem(row, c, dash_item)
        row += 1

        # 정확 중복 그룹 안 파일들은 바이트 단위로 동일해서 EXIF/용량으로는
        # 구분이 안 되므로(core/duplicate_resolver.py 참고), 이 조합에 속한
        # 모든 그룹이 같은 폴더를 추천할 때만 그 폴더를 기본 선택으로 미리
        # 골라준다 — 신뢰도 낮으면 지금처럼 "건너뛰기"가 기본값으로 남는다.
        suggested_folder = suggest_keep_folder(group_list)

        radios: list[QRadioButton] = []
        all_child_rows: list[int] = []  # 끝에서 한꺼번에 숨김 처리 — 아래 주석 참고
        for folder in folders:
            table.insertRow(row)

            radio = QRadioButton()
            radio.setToolTip("이 폴더의 파일을 남깁니다")
            button_group.addButton(radio)
            radios.append(radio)
            table.setCellWidget(row, 0, radio)

            toggle_btn = QToolButton()
            toggle_btn.setText(f"▸ {folder}")
            toggle_btn.setCheckable(True)
            toggle_btn.setAutoRaise(True)
            toggle_btn.setCursor(Qt.PointingHandCursor)
            toggle_btn.setToolTip(f"{folder}\n눌러서 이 폴더를 남기도록 선택하고, 지워질 파일도 같이 확인하세요")
            toggle_btn.setStyleSheet(
                "QToolButton { border: none; background: transparent; text-align: left; }"
            )
            # 폴더명(이 버튼)을 누르면 펼침/접힘만 되고 실제 라디오 선택은
            # 안 바뀌던 문제(2026-09-17, 사용자 리포트 — 폴더명을 눌러서
            # "이걸 남기겠다"고 골랐다고 생각했는데 실제로는 선택이 안 바뀌어
            # 반대 폴더가 지워짐) — 폴더명을 누르면 라디오도 같이 선택되게
            # 한다. toggled가 아니라 clicked에 건다: toggled는 펼침 상태가
            # "바뀔 때만" 오는데(이미 펼쳐둔 걸 다시 누르면 접히기만 하고
            # 다시 안 옴), 라디오 선택은 매번 누를 때마다 반영돼야 한다.
            toggle_btn.clicked.connect(lambda _checked=False, r=radio: r.setChecked(True))
            table.setCellWidget(row, 1, toggle_btn)

            keep_status_item = QTableWidgetItem("유지")
            table.setItem(row, 2, keep_status_item)

            is_recommended = suggested_folder is not None and suggested_folder[0] == folder
            reason_text = f"추천 — {suggested_folder[1]}" if is_recommended else ""
            if reason_text:
                table.setCellWidget(row, 3, self._reason_label(reason_text))
            else:
                table.setItem(row, 3, QTableWidgetItem(""))

            row += 1
            child_rows: list[int] = []
            for idx, group in enumerate(group_list, start=1):
                remove_infos = [info for info in group if Path(info.path).parent != folder]
                for info in remove_infos:
                    table.insertRow(row)
                    # 잘리지 않고 다 보이게 아래에서 resizeRowsToContents()로
                    # 실제 높이를 계산한 "뒤"에 숨긴다 — gui/duplicate_screen.py
                    # ::_build_auto_table과 같은 이유(2026-09-08, 사용자 리포트
                    # — "사유가 짤리는데 툴팁도 안 보여").
                    all_child_rows.append(row)

                    blank0 = QTableWidgetItem("")
                    blank0.setFlags(Qt.NoItemFlags)
                    table.setItem(row, 0, blank0)

                    file_item = QTableWidgetItem(f"└ {info.filename}")
                    file_item.setToolTip(f"{info.path}\n더블클릭: 미리보기 · 우클릭: 폴더 열기 등")
                    # (info, group) 튜플로 저장 — 미리보기에서 방향키로 같은
                    # 그룹의 다음/이전 사진으로 넘어갈 수 있게 group도 같이
                    # 들고 있는다(2026-09-08, 사용자 요청).
                    file_item.setData(Qt.UserRole, (info, group))
                    table.setItem(row, 1, file_item)

                    del_status_item = QTableWidgetItem("삭제")
                    table.setItem(row, 2, del_status_item)

                    group_item = QTableWidgetItem(f"그룹 {idx}")
                    table.setItem(row, 3, group_item)

                    for it in (file_item, del_status_item, group_item):
                        it.setForeground(QColor(COLORS["text_secondary"]))

                    child_rows.append(row)
                    row += 1

            def _make_toggle_handler(btn=toggle_btn, rows=child_rows, folder=folder, table=table):
                def _handler(checked: bool) -> None:
                    btn.setText(f"▾ {folder}" if checked else f"▸ {folder}")
                    for r in rows:
                        table.setRowHidden(r, not checked)
                    self._resize_auto_table_height(table)

                return _handler

            toggle_btn.toggled.connect(_make_toggle_handler())

        # 기본값: 추천이 있으면 추천 폴더를, 없으면 여전히 "건너뛰기"를 선택
        if suggested_folder is not None:
            for folder, radio in zip(folders, radios):
                if folder == suggested_folder[0]:
                    radio.setChecked(True)
                    break
            else:
                skip_radio.setChecked(True)
        else:
            skip_radio.setChecked(True)

        # 모든 행이 아직 "보이는" 상태일 때 실제 필요한 높이(줄바꿈 포함)를
        # 계산한 뒤에야 하위 행을 숨긴다 — 순서를 바꾸면 숨긴 행의 높이가
        # 0으로 계산돼 나중에 펼쳐도 계속 잘려 보인다.
        table.resizeRowsToContents()
        for r in all_child_rows:
            table.setRowHidden(r, True)

        self._resize_auto_table_height(table)  # 이름은 "auto"지만 어떤 QTableWidget에도 쓸 수 있는 범용 계산
        return table, folders, radios, skip_radio, suggested_folder

    def _cluster_row_file_info(self, table: QTableWidget, row: int):
        """조합 표 하나 안에서 row가 가리키는 (FileInfo, group) 튜플 — 펼쳐진
        하위(삭제될 파일) 행에만 실제 파일이 있다("건너뛰기"/폴더 후보 행
        자체는 폴더를 나타낼 뿐 미리볼 사진 하나로 정해지지 않는다). group은
        미리보기에서 방향키로 같은 그룹의 다음/이전 사진으로 넘어갈 때 쓴다."""
        item = table.item(row, 1)
        return item.data(Qt.UserRole) if item else None

    def _on_cluster_row_double_clicked(self, table: QTableWidget, index) -> None:
        if index.column() == 0:
            return
        found = self._cluster_row_file_info(table, index.row())
        if found is not None:
            info, group = found
            self.file_selected.emit(info, group)

    def _on_cluster_context_menu(self, table: QTableWidget, pos) -> None:
        index = table.indexAt(pos)
        if not index.isValid() or index.column() == 0:
            return
        found = self._cluster_row_file_info(table, index.row())
        if found is None:
            return
        info, group = found

        menu = QMenu(self)
        preview_action = menu.addAction("미리보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen is preview_action:
            self.file_selected.emit(info, group)
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _build_group_card(
        self, idx: int, group: list
    ) -> tuple[QFrame, list[QRadioButton], QRadioButton, tuple | None]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        header = QLabel(f"그룹 {idx} · {len(group)}개 파일 · 각 {format_file_size(group[0].file_size)}")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        suggested_keep = suggest_keep(group)
        if suggested_keep is not None:
            hint = QLabel(f"추천: '{Path(suggested_keep[0].path).name}' 유지 — {suggested_keep[1]}")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {COLORS['primary']}; font-size: 11px;")
            layout.addWidget(hint)

        button_group = QButtonGroup(card)

        skip_radio = QRadioButton("이 그룹은 정리하지 않음(건너뛰기)")
        skip_radio.setStyleSheet(f"color: {COLORS['text_secondary']};")
        button_group.addButton(skip_radio)
        layout.addWidget(skip_radio)

        radios: list[QRadioButton] = []
        for info in group:
            row = QHBoxLayout()
            radio = QRadioButton()
            radio.setToolTip("이 파일을 남깁니다")
            button_group.addButton(radio)
            radios.append(radio)
            row.addWidget(radio)

            path_label = _ClickableLabel(info.path)
            path_label.setWordWrap(True)
            path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            path_label.setToolTip("눌러서 이 파일을 남기도록 선택하고, 사진도 같이 확인하세요")

            def _on_path_clicked(info=info, r=radio):
                # 경로를 눌러도 미리보기만 열리고 라디오 선택은 안 바뀌던 문제
                # (위 _build_cluster_table과 같은 이유로 발견) — 경로를 누르면
                # "이 파일을 남긴다" 선택도 같이 되게 한다.
                r.setChecked(True)
                self.file_selected.emit(info, group)

            path_label.clicked.connect(_on_path_clicked)
            row.addWidget(path_label, stretch=1)
            layout.addLayout(row)

        # 기본값: 추천이 있으면 추천 파일을, 없으면 여전히 "건너뛰기"를 선택
        if suggested_keep is not None:
            for info, radio in zip(group, radios):
                if info is suggested_keep[0]:
                    radio.setChecked(True)
                    break
            else:
                skip_radio.setChecked(True)
        else:
            skip_radio.setChecked(True)

        return card, radios, skip_radio, suggested_keep

    def _build_auto_table(self, auto_rows: list[tuple[list, object, str]]) -> QTableWidget:
        """"확신 가능" 그룹을 체크박스 표 한 줄씩으로 보여준다 — 그룹마다 카드를
        만들면 재정리 버그처럼 수백 그룹이 한꺼번에 생겼을 때 스크롤이 끝없이
        길어지는 문제가 있어서, gui/result_screen.py의 CheckAllHeaderView
        체크박스 테이블 패턴을 그대로 재사용했다(같은 원리로 이미 수천 행에서
        성능 검증됨). 표 자체는 스크롤바 없이 행 수만큼 정확히 늘어나서, 화면
        전체를 감싸는 바깥 QScrollArea 하나로만 스크롤된다(표 안/밖 이중
        스크롤을 피하기 위함).

        "삭제될 파일"을 개수로만 보여주던 대신, 엑셀 "행 그룹화"처럼 부모
        행 바로 아래 실제 표 행으로 펼쳐서 어떤 파일이 왜 지워지는지 확인할
        수 있다(2026-09-08, 사용자 요청 — "삭제될 파일을 확인할 수가 없어",
        "생성일이 빠르다고 삭제될 이유가 되는 게 아니잖아" — 자동 추천을
        맹목적으로 믿지 않고 직접 확인하고 싶다는 피드백. 한 셀 안에 다
        쌓아 보여주는 1차 시도는 "그게 아니야"로 거부당해서
        experiments/auto_table_grouping_prototype에서 검증받았다). 칸 구성은
        "체크옵션 / 파일명(로컬주소) / 구분 / 사유"로 통일했다(2차 피드백 —
        "남길 파일"/"삭제될 파일"을 별도 칸으로 나누지 말고 "구분" 칸에
        유지/삭제로만 표시, ▾는 파일명 칸 자체에 붙여서 그 칸을 누르면
        펼쳐지게, experiments/cluster_grouping_prototype에서 검증받음 —
        gui/duplicate_screen.py의 폴더 단위 표와 같은 모양). 하위 행은 기본
        숨김(setRowHidden)이고 부모 행(파일명 칸)을 눌러야만 열리고 닫힌다 —
        self._auto_parent_rows[auto_rows 인덱스] = 그 그룹의 부모 행이 표에서
        실제로 위치한 행 번호(하위 행이 끼어들며 더 이상 인덱스와 행 번호가
        같지 않다)."""
        table = QTableWidget(0, 4)
        header = CheckAllHeaderView(table)
        header.set_checked(True)  # 기본 전체 선택 — 카드 하나였을 때도 추천이 있으면 기본 선택이었음
        header.toggled.connect(self._set_all_auto_checked)
        table.setHorizontalHeader(header)
        table.setHorizontalHeaderLabels(["", "파일명 (로컬주소)", "구분", "사유"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        table.setColumnWidth(0, 32)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setColumnWidth(2, 60)
        table.setColumnWidth(3, 260)  # 사유가 기본 폭으로는 많이 잘려서 넉넉하게(그래도 다 안 보이면 툴팁)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # col1이 Stretch라 표 자체는 가로 스크롤이 필요 없다 — 없으면 표
        # 위젯이 실제 창 폭보다 좁게 배치될 때 "사유" 칸이 표 자체의 가로
        # 스크롤 뒤로 밀려 숨어버릴 수 있다(2026-09-08, 사용자 리포트 —
        # "사유가 안 보인다"의 진짜 원인 — 바깥 QScrollArea만 막아뒀지 표
        # 자신의 가로 스크롤은 안 막아뒀었음).
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setFocusPolicy(Qt.NoFocus)
        table.doubleClicked.connect(self._on_auto_row_double_clicked)
        # 폴더 경로를 칸 안에 같이 적으면 좁은 폭에서 다 안 보였다(2026-09-08,
        # 사용자 리포트) — 파일명만 보여주고, 폴더 경로가 필요하면 우클릭
        # 메뉴로 확인하게 한다(gui/result_screen.py의 검사 결과 표와 같은
        # 패턴 — "미리보기"/"로컬 폴더 위치 열기").
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_auto_context_menu)

        self._auto_parent_rows = []
        all_child_rows: list[int] = []  # 끝에서 한꺼번에 숨김 처리 — 이유는 아래 참고

        table.setUpdatesEnabled(False)
        try:
            row = 0
            for group, keep_info, reason in auto_rows:
                table.insertRow(row)
                self._auto_parent_rows.append(row)

                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Checked)
                table.setItem(row, 0, check_item)

                removed = [info for info in group if info is not keep_info]
                toggle_btn = QToolButton()
                toggle_btn.setText(f"▸ {keep_info.filename}")
                toggle_btn.setCheckable(True)
                toggle_btn.setAutoRaise(True)
                toggle_btn.setCursor(Qt.PointingHandCursor)
                toggle_btn.setToolTip(f"{keep_info.path}\n눌러서 삭제될 파일을 확인하세요")
                toggle_btn.setStyleSheet(
                    "QToolButton { border: none; background: transparent; text-align: left; }"
                )
                table.setCellWidget(row, 1, toggle_btn)

                keep_status_item = QTableWidgetItem("유지")
                table.setItem(row, 2, keep_status_item)

                table.setCellWidget(row, 3, self._reason_label(reason))

                row += 1
                child_rows: list[int] = []
                for info in removed:
                    table.insertRow(row)
                    # 잘리지 않고 다 보이게(PicMedic 원칙 — 절대 자르지 않고
                    # 줄바꿈/행 높이로 늘린다) 아래에서 resizeRowsToContents()로
                    # 실제 높이를 계산한 "뒤"에 숨긴다 — 숨긴 상태로 계산하면
                    # Qt가 높이를 0으로 취급해서 나중에 펼쳐도 줄바꿈된 내용이
                    # 계속 잘려 보이는 문제가 있었다(2026-09-08, 사용자 리포트
                    # — "사유가 짤리는데 툴팁도 안 보여").
                    all_child_rows.append(row)

                    blank0 = QTableWidgetItem("")
                    blank0.setFlags(Qt.NoItemFlags)
                    table.setItem(row, 0, blank0)

                    file_item = QTableWidgetItem(f"└ {info.filename}")
                    file_item.setToolTip(f"{info.path}\n더블클릭: 미리보기 · 우클릭: 폴더 열기 등")
                    # (info, group) 튜플로 저장 — 미리보기에서 방향키로 같은
                    # 그룹의 다음/이전 사진으로 넘어갈 수 있게 group도 같이
                    # 들고 있는다(2026-09-08, 사용자 요청).
                    file_item.setData(Qt.UserRole, (info, group))
                    table.setItem(row, 1, file_item)

                    del_status_item = QTableWidgetItem("삭제")
                    table.setItem(row, 2, del_status_item)

                    per_file_reason = explain_file(info, group)
                    reason_label = self._reason_label(per_file_reason)
                    reason_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
                    table.setCellWidget(row, 3, reason_label)

                    for it in (file_item, del_status_item):
                        it.setForeground(QColor(COLORS["text_secondary"]))

                    child_rows.append(row)
                    row += 1

                def _make_toggle_handler(btn=toggle_btn, rows=child_rows, table=table, keep_info=keep_info):
                    def _handler(checked: bool) -> None:
                        btn.setText(f"▾ {keep_info.filename}" if checked else f"▸ {keep_info.filename}")
                        for r in rows:
                            table.setRowHidden(r, not checked)
                        self._resize_auto_table_height(table)

                    return _handler

                toggle_btn.toggled.connect(_make_toggle_handler())

            # 모든 행이 아직 "보이는" 상태일 때 실제 필요한 높이(줄바꿈 포함)를
            # 계산한 뒤에야 하위 행을 숨긴다 — 순서를 바꾸면 숨긴 행의 높이가
            # 0으로 계산돼 나중에 펼쳐도 계속 잘려 보인다.
            table.resizeRowsToContents()
            for r in all_child_rows:
                table.setRowHidden(r, True)
        finally:
            table.setUpdatesEnabled(True)

        table.itemChanged.connect(self._on_auto_item_changed)
        self._resize_auto_table_height(table)
        return table

    def _rebuild_auto_table(self) -> None:
        """자동 추천 표는 부모 행 + 숨겨진 하위(삭제될 파일) 행이 섞여 있어서
        (엑셀 행 그룹화 스타일) 정리 실행 후 일부 행만 골라 지우면 부모/하위
        행 번호가 뒤섞이기 쉽다 — 남은 self._auto_rows로 표를 통째로 다시
        만드는 편이 훨씬 안전하다(set_result() 때처럼 업데이트를 잠그고
        다시 그려서 수백 행이어도 충분히 빠르다)."""
        if self._auto_table is None:
            return
        old_table = self._auto_table
        index = self._list_layout.indexOf(old_table)
        new_table = self._build_auto_table(self._auto_rows)
        self._list_layout.insertWidget(index, new_table)
        self._list_layout.removeWidget(old_table)
        # removeWidget()은 레이아웃 관리에서만 뺄 뿐 위젯을 바로 숨기거나
        # 없애지 않는다 — deleteLater()가 실제로 처리되기 전까지 마지막
        # 위치에 그대로 남아 새 표 위에 겹쳐 보이는 문제가 있었다(2026-09-08).
        # 명시적으로 숨겨서 그 틈에도 보이지 않게 한다.
        old_table.hide()
        old_table.deleteLater()
        self._auto_table = new_table

    def _resize_auto_table_height(self, table: QTableWidget) -> None:
        """표가 자기 행 수만큼만 높이를 차지하게 고정한다(내부 스크롤 없이) —
        바깥 QScrollArea 하나로만 페이지 전체가 스크롤되게 하기 위함."""
        height = table.horizontalHeader().height() + table.verticalHeader().length() + 2 * table.frameWidth() + 2
        table.setFixedHeight(height)

    def _reason_label(self, text: str) -> QLabel:
        """"사유" 칸에 넣을 줄바꿈 라벨 — QTableWidgetItem의 wordWrap보다
        QLabel(wordWrap=True) 위젯 칸이 resizeRowsToContents()와 훨씬
        안정적으로 맞아떨어져서 이 방식을 쓴다(2026-09-08, 사용자 리포트 —
        item 방식은 실사용 환경에서 한 줄로 "..." 잘려 보이는 경우가 있었음).
        폭을 칼럼 폭(260px)에 맞춰 미리 고정해둬야 셀에 배치되기 전에도
        줄바꿈 높이를 정확히 계산할 수 있다."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(240)
        label.setContentsMargins(4, 4, 4, 4)
        return label

    def _set_all_auto_checked(self, checked: bool) -> None:
        if not self._auto_table:
            return
        state = Qt.Checked if checked else Qt.Unchecked
        self._auto_table.blockSignals(True)
        for row in self._auto_parent_rows:
            item = self._auto_table.item(row, 0)
            if item:
                item.setCheckState(state)
        self._auto_table.blockSignals(False)

    def _on_auto_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or not self._auto_table:
            return
        total = len(self._auto_parent_rows)
        checked = sum(
            1
            for r in self._auto_parent_rows
            if self._auto_table.item(r, 0) and self._auto_table.item(r, 0).checkState() == Qt.Checked
        )
        header = self._auto_table.horizontalHeader()
        if isinstance(header, CheckAllHeaderView):
            header.set_checked(total > 0 and checked == total)

    def _auto_row_file_info(self, row: int):
        """표의 행 번호(row) 하나가 가리키는 (FileInfo, group) 튜플을 찾는다
        — 부모 행이면 "남길 파일"(keep_info) + 그 그룹, 펼쳐진 하위 행이면
        그 "삭제될 파일" 자신 + 같은 그룹. 더블클릭 미리보기와 우클릭 메뉴
        둘 다 이 조회를 그대로 쓴다. group은 미리보기에서 방향키로 같은
        그룹의 다음/이전 사진으로 넘어갈 때 쓴다."""
        if row in self._auto_parent_rows:
            auto_idx = self._auto_parent_rows.index(row)
            group, keep_info, _reason = self._auto_rows[auto_idx]
            return keep_info, group
        item = self._auto_table.item(row, 1) if self._auto_table else None
        return item.data(Qt.UserRole) if item else None

    def _on_auto_row_double_clicked(self, index) -> None:
        if index.column() == 0:
            return  # 체크박스 칸은 미리보기로 넘기지 않는다
        found = self._auto_row_file_info(index.row())
        if found is not None:
            info, group = found
            self.file_selected.emit(info, group)

    def _on_auto_context_menu(self, pos) -> None:
        if not self._auto_table:
            return
        index = self._auto_table.indexAt(pos)
        if not index.isValid() or index.column() == 0:
            return
        found = self._auto_row_file_info(index.row())
        if found is None:
            return  # 체크박스 칸 등 — 이 지점에선 도달하지 않지만 방어적으로 둠
        info, group = found

        menu = QMenu(self)
        preview_action = menu.addAction("미리보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        chosen = menu.exec(self._auto_table.viewport().mapToGlobal(pos))
        if chosen is preview_action:
            self.file_selected.emit(info, group)
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _on_cleanup_clicked(self):
        # 그룹 단위로 모아둔다(파일별 flat 목록이 아니라) — 임시 휴지통에
        # 옮길 때 그룹마다 서브폴더 + "왜 옮겨졌는지" 사유를 남기기 위함
        # (utils/trash.py::create_trash_group). 튜플: (남길 파일 경로, 옮길
        # FileInfo 목록, 사유 텍스트). entry_refs는 to_process와 인덱스가 1:1로
        # 맞는 병렬 목록 — 워커가 끝난 뒤 "이 카드/행을 지워도 되는지"를
        # 판단하는 데 쓴다(gui/trash_worker.py 참고).
        to_process: list[tuple[str, list, str]] = []
        entry_refs: list[tuple[str, object]] = []

        for entry in self._cluster_entries:
            if entry.skip_radio.isChecked():
                continue
            keep_folder = next(
                (folder for folder, radio in zip(entry.folder_options, entry.radios) if radio.isChecked()),
                None,
            )
            if keep_folder is None:
                continue  # 이론상 도달 안 함(라디오 그룹이라 항상 하나는 선택됨)
            auto_applied = entry.suggested_folder is not None and entry.suggested_folder[0] == keep_folder
            for group in entry.group_list:
                remove_infos = [info for info in group if Path(info.path).parent != keep_folder]
                keep_info = next(info for info in group if Path(info.path).parent == keep_folder)
                if remove_infos:
                    if auto_applied:
                        reason = f"자동 추천 적용 — {entry.suggested_folder[1]} (폴더: '{keep_folder}')"
                    else:
                        reason = f"폴더 단위 정리 — '{keep_folder}' 폴더를 남기기로 선택해서 이 파일들이 이동됨"
                    to_process.append((keep_info.path, remove_infos, reason))
                    entry_refs.append(("cluster", entry))

        if self._auto_table:
            for auto_idx, (group, keep_info, reason) in enumerate(self._auto_rows):
                table_row = self._auto_parent_rows[auto_idx]
                item = self._auto_table.item(table_row, 0)
                if not item or item.checkState() != Qt.Checked:
                    continue  # 체크 해제 = 이 행은 건너뛰기
                remove_infos = [info for info in group if info is not keep_info]
                if remove_infos:
                    to_process.append((keep_info.path, remove_infos, f"자동 추천 적용 — {reason}"))
                    entry_refs.append(("auto", auto_idx))

        for entry in self._manual_entries:
            if entry.skip_radio.isChecked():
                continue
            keep_info = None
            remove_infos = []
            for info, radio in zip(entry.group, entry.radios):
                if radio.isChecked():
                    keep_info = info
                else:
                    remove_infos.append(info)
            if remove_infos and keep_info is not None:
                auto_applied = entry.suggested_keep is not None and entry.suggested_keep[0] is keep_info
                if auto_applied:
                    reason = f"자동 추천 적용 — {entry.suggested_keep[1]}"
                else:
                    reason = f"개별 그룹 정리 — '{Path(keep_info.path).name}' 파일을 남기고 이 파일들이 이동됨"
                to_process.append((keep_info.path, remove_infos, reason))
                entry_refs.append(("manual", entry))

        total_to_remove = sum(len(infos) for _, infos, _ in to_process)
        if not total_to_remove:
            # 전부 "건너뛰기"거나 정리할 그룹이 아예 없음 — 할 일 없음
            info_dialog(self, "정리할 파일을 선택하지 않았어요.\n남길 파일(또는 폴더)을 먼저 골라주세요.")
            return

        confirmed = confirm_dialog(
            self,
            f"선택한 {total_to_remove}개 파일을 임시 휴지통으로 옮길게요.\n\n"
            "완전히 삭제되는 게 아니라서 나중에 원래 위치로 복원할 수 있어요.",
            confirm_text="이동",
            cancel_text="취소",
        )
        if not confirmed:
            return

        self._pending_entry_refs = entry_refs
        self._worker = TrashMoveWorker(to_process, self)
        self._worker.progress.connect(self._on_cleanup_progress)
        self._worker.finished_batch.connect(self._on_cleanup_finished)
        self.progress_dialog.start("임시 휴지통으로 옮기는 중")
        self._worker.start()
        self.progress_dialog.exec()

    def _on_cleanup_progress(self, current: int, total: int, filename: str) -> None:
        self.progress_dialog.update_progress(current, total, filename)

    def _on_cleanup_cancel_requested(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_cleanup_finished(self, moved: int, failed: list, moved_infos: list, completed_entry_indices: list) -> None:
        self.progress_dialog.accept()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait()

        # 검사 결과에서도 빼야 다음에 "중복 파일 보기"를 다시 눌렀을 때 이미
        # 옮긴 파일이 또 중복으로 잡혀 되살아나 보이지 않는다.
        if self._result is not None:
            for info in moved_infos:
                self._result.remove(info)

        if failed:
            info_dialog(
                self,
                f"{moved}개 파일을 임시 휴지통으로 옮겼습니다.\n"
                f"{len(failed)}개는 옮기지 못했습니다:\n" + "\n".join(failed),
            )
        else:
            info_dialog(self, f"{moved}개 파일을 임시 휴지통으로 옮겼습니다.\n확인해주세요.")

        # 취소로 인해 아예 시도조차 안 된 카드/행은 다음에 다시 볼 수 있게
        # 화면에 그대로 남긴다 — completed_entry_indices에 있는 것만 지운다.
        entry_refs = self._pending_entry_refs or []
        self._pending_entry_refs = None
        resolved_clusters: set = set()
        resolved_auto_rows: list[int] = []
        resolved_manual: set = set()
        for idx in completed_entry_indices:
            kind, ref = entry_refs[idx]
            if kind == "cluster":
                resolved_clusters.add(ref)
            elif kind == "auto":
                resolved_auto_rows.append(ref)
            elif kind == "manual":
                resolved_manual.add(ref)

        for entry in resolved_clusters:
            self._cluster_entries.remove(entry)
            entry.card.deleteLater()
        if resolved_auto_rows:
            # self._auto_parent_rows 인덱스 == self._auto_rows 인덱스이므로
            # (표의 실제 행 번호와는 다름, _build_auto_table 참고) 여기서는
            # 그대로 self._auto_rows에서 지우면 되지만, 표 자체는 부모/하위
            # 행이 섞여 있어 일부만 removeRow()하면 번호가 꼬이기 쉬워
            # 통째로 다시 만든다(_rebuild_auto_table 참고).
            for idx in sorted(set(resolved_auto_rows), reverse=True):
                del self._auto_rows[idx]
            self._rebuild_auto_table()
        for entry in resolved_manual:
            self._manual_entries.remove(entry)
            entry.card.deleteLater()
        self._refresh_summary()

        if moved:
            self.view_trash_requested.emit(moved_infos)
