"""
gui/duplicate_screen.py

Phase 2 "사진 정리" 1차 범위 — 정확 중복(파일 내용 SHA-256) 탐지 결과를 보여주고,
남길 파일을 고르면 나머지를 임시 휴지통으로 옮긴다(완전 삭제 아님 — utils/trash.py
참고, "원본 보호" 원칙과 절충). PHASE2_사진정리_기획.md 참고. 다시 스캔하지 않고,
같은 검사 세션에서 이미 계산된 FileInfo.content_hash로 ScanResult.duplicate_groups()
를 호출해 그룹만 보여준다.

중복 그룹이 수백 개면 그룹마다 하나씩 고르는 게 비현실적이라(실사용 리포트:
680개 그룹), "폴더째로 중복"인 흔한 경우를 자동으로 묶어서 처리한다:
- 그룹 안 파일들이 전부 서로 다른 폴더에 있으면 -> 그 폴더 조합(frozenset)별로
  같은 패턴의 그룹들을 한데 묶고, "이 폴더 남기기"를 한 번만 고르면 그 조합에
  속한 모든 그룹에 일괄 적용된다.
- 그룹 안에 같은 폴더 파일이 2개 이상이면(폴더만으로는 구분 불가) -> 기존처럼
  파일 하나하나 라디오로 고르게 한다(개별 확인 필요, 보통 소수).

모든 조합/그룹에는 "정리하지 않음"(건너뛰기) 선택지도 있고 기본값이다 — 아무
것도 안 고르면 그 파일들은 그대로 둔다. 정리를 실행하면 실제로 처리된
(건너뛰지 않은) 카드만 화면에서 사라지고, 건너뛴 카드는 나중에 다시 볼 수
있게 그대로 남는다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QFrame,
    QScrollArea,
)

from gui.common_dialogs import confirm_dialog, info_dialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS
from utils import trash
from utils.file_utils import format_file_size

SKIP_LABEL = "이 조합은 정리하지 않음(건너뛰기)"


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

    __slots__ = ("card", "group_list", "folder_options", "radios", "skip_radio")

    def __init__(self, card, group_list, folder_options, radios, skip_radio):
        self.card = card
        self.group_list = group_list
        self.folder_options = folder_options
        self.radios = radios
        self.skip_radio = skip_radio

    @property
    def group_count(self) -> int:
        return len(self.group_list)


class _ManualEntry:
    """폴더만으로는 못 정하는(같은 폴더 안 중복) 그룹 카드 하나의 상태."""

    __slots__ = ("card", "group", "radios", "skip_radio")

    def __init__(self, card, group, radios, skip_radio):
        self.card = card
        self.group = group
        self.radios = radios
        self.skip_radio = skip_radio


class DuplicateScreen(QWidget):
    """검사 결과 화면(gui/result_screen.py)의 "중복 파일 보기" 버튼으로 들어오는
    화면. 같은 스캔 세션(gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    view_trash_requested = Signal()  # 정리(휴지통 이동) 완료 후 휴지통 화면으로 이동

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None  # 정리(휴지통 이동) 후 옮긴 파일을 여기서도 빼야 재조회 시 다시 안 나타남
        self._cluster_entries: list[_ClusterEntry] = []
        self._manual_entries: list[_ManualEntry] = []
        self._cluster_section: QLabel | None = None
        self._manual_section: QLabel | None = None

        outer = QVBoxLayout(self)
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
            "같은 폴더 안에 중복이 있는 경우만 파일을 하나씩 골라주세요. "
            "정리하고 싶지 않은 조합/그룹은 \"건너뛰기\"를 그대로 두면 손대지 않아요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel("중복된 파일이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll_area.setWidget(self._list_container)
        outer.addWidget(self.scroll_area, stretch=1)

        self.cleanup_btn = QPushButton("선택한 파일 임시 휴지통으로 이동")
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
        self._manual_entries = []

        self.setUpdatesEnabled(False)
        try:
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            clusters, manual = _cluster_by_folder(groups)

            row = 0
            self._cluster_section = QLabel()
            self._cluster_section.setStyleSheet("font-weight: 700;")
            self._list_layout.insertWidget(row, self._cluster_section)
            row += 1
            # 그룹을 많이 해결해주는 조합을 위로
            for key in sorted(clusters, key=lambda k: len(clusters[k]), reverse=True):
                group_list = clusters[key]
                card, folder_options, radios, skip_radio = self._build_cluster_card(sorted(key), group_list)
                self._cluster_entries.append(
                    _ClusterEntry(card, group_list, folder_options, radios, skip_radio)
                )
                self._list_layout.insertWidget(row, card)
                row += 1

            self._manual_section = QLabel()
            self._manual_section.setStyleSheet("font-weight: 700; margin-top: 8px;")
            self._list_layout.insertWidget(row, self._manual_section)
            row += 1
            for idx, group in enumerate(manual, start=1):
                card, radios, skip_radio = self._build_group_card(idx, group)
                self._manual_entries.append(_ManualEntry(card, group, radios, skip_radio))
                self._list_layout.insertWidget(row, card)
                row += 1

            self._refresh_summary()
        finally:
            self.setUpdatesEnabled(True)

    def has_pending(self) -> bool:
        """정리할 그룹/조합이 아직 남아있는지 — 임시 휴지통에서 뒤로 나올 때
        빈 화면을 거치지 않고 검사 결과로 바로 보낼지 판단하는 데 쓰인다."""
        return bool(self._cluster_entries or self._manual_entries)

    def _refresh_summary(self) -> None:
        """칩/빈 상태/섹션 제목을 지금 남아있는 카드(_cluster_entries/_manual_entries)
        기준으로 다시 계산한다 — 정리 실행 후 일부(건너뛴 것)만 남을 때도 이걸로
        섹션 제목의 개수 표시가 같이 갱신되게 한다."""
        group_count = sum(e.group_count for e in self._cluster_entries) + len(self._manual_entries)
        file_count = sum(len(g) for e in self._cluster_entries for g in e.group_list) + sum(
            len(e.group) for e in self._manual_entries
        )
        has_any = bool(self._cluster_entries or self._manual_entries)

        self.group_chip.set_value(group_count)
        self.file_chip.set_value(file_count)
        self.cluster_chip.set_value(len(self._cluster_entries))
        self.empty_label.setVisible(not has_any)
        self.scroll_area.setVisible(has_any)
        self.cleanup_btn.setEnabled(has_any)

        self._cluster_section.setVisible(bool(self._cluster_entries))
        if self._cluster_entries:
            self._cluster_section.setText(f"폴더 단위로 정리 가능 · {len(self._cluster_entries)}개 조합")

        self._manual_section.setVisible(bool(self._manual_entries))
        if self._manual_entries:
            self._manual_section.setText(
                f"개별로 확인 필요 · {len(self._manual_entries)}개 그룹 (같은 폴더 안 중복)"
            )

    def _build_cluster_card(
        self, folders: list[Path], group_list: list[list]
    ) -> tuple[QFrame, list[Path], list[QRadioButton], QRadioButton]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        header = QLabel(f"폴더 {len(folders)}개 조합 · {len(group_list)}개 그룹에 적용")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        sub = QLabel("남길 폴더를 선택하세요 — 나머지 폴더의 파일들이 정리 대상이 됩니다.")
        sub.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(sub)

        button_group = QButtonGroup(card)

        skip_radio = QRadioButton(SKIP_LABEL)
        skip_radio.setChecked(True)  # 기본값: 아무 파일도 건드리지 않음
        skip_radio.setStyleSheet(f"color: {COLORS['text_secondary']};")
        button_group.addButton(skip_radio)
        layout.addWidget(skip_radio)

        radios: list[QRadioButton] = []
        for folder in folders:
            row = QHBoxLayout()
            radio = QRadioButton()
            radio.setToolTip("이 폴더의 파일을 남깁니다")
            button_group.addButton(radio)
            radios.append(radio)
            row.addWidget(radio)

            path_label = QLabel(str(folder))
            path_label.setWordWrap(True)
            path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            row.addWidget(path_label, stretch=1)
            layout.addLayout(row)

        return card, folders, radios, skip_radio

    def _build_group_card(self, idx: int, group: list) -> tuple[QFrame, list[QRadioButton], QRadioButton]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        header = QLabel(f"그룹 {idx} · {len(group)}개 파일 · 각 {format_file_size(group[0].file_size)}")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        button_group = QButtonGroup(card)

        skip_radio = QRadioButton("이 그룹은 정리하지 않음(건너뛰기)")
        skip_radio.setChecked(True)  # 기본값: 아무 파일도 건드리지 않음
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

            path_label = QLabel(info.path)
            path_label.setWordWrap(True)
            path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            row.addWidget(path_label, stretch=1)
            layout.addLayout(row)

        return card, radios, skip_radio

    def _on_cleanup_clicked(self):
        to_remove = []
        resolved_clusters: list[_ClusterEntry] = []
        resolved_manual: list[_ManualEntry] = []

        for entry in self._cluster_entries:
            if entry.skip_radio.isChecked():
                continue
            keep_folder = next(
                (folder for folder, radio in zip(entry.folder_options, entry.radios) if radio.isChecked()),
                None,
            )
            if keep_folder is None:
                continue  # 이론상 도달 안 함(라디오 그룹이라 항상 하나는 선택됨)
            for group in entry.group_list:
                for info in group:
                    if Path(info.path).parent != keep_folder:
                        to_remove.append(info)
            resolved_clusters.append(entry)

        for entry in self._manual_entries:
            if entry.skip_radio.isChecked():
                continue
            for info, radio in zip(entry.group, entry.radios):
                if not radio.isChecked():
                    to_remove.append(info)
            resolved_manual.append(entry)

        if not to_remove:
            # 전부 "건너뛰기"거나 정리할 그룹이 아예 없음 — 할 일 없음
            info_dialog(self, "정리할 파일을 선택하지 않았어요.\n남길 파일(또는 폴더)을 먼저 골라주세요.")
            return

        confirmed = confirm_dialog(
            self,
            f"선택한 {len(to_remove)}개 파일을 임시 휴지통으로 이동합니다.\n"
            "원본은 삭제되지 않고 옮겨지기만 하며, 나중에 직접 확인할 수 있어요.\n"
            "건너뛰기로 둔 항목은 그대로 남아있어요.\n계속할까요?",
            confirm_text="이동",
            cancel_text="취소",
        )
        if not confirmed:
            return

        moved = 0
        for info in to_remove:
            try:
                trash.move_to_trash(info.path)
                moved += 1
                # 검사 결과에서도 빼야 다음에 "중복 파일 보기"를 다시 눌렀을 때
                # 이미 옮긴 파일이 또 중복으로 잡혀 되살아나 보이지 않는다.
                if self._result is not None:
                    self._result.remove(info)
            except OSError:
                continue

        info_dialog(self, f"{moved}개 파일을 임시 휴지통으로 옮겼습니다.\n확인해주세요.")

        # 실제로 처리된 카드만 화면에서 지우고, 건너뛴 카드는 다시 볼 수 있게 남긴다.
        for entry in resolved_clusters:
            self._cluster_entries.remove(entry)
            entry.card.deleteLater()
        for entry in resolved_manual:
            self._manual_entries.remove(entry)
            entry.card.deleteLater()
        self._refresh_summary()

        self.view_trash_requested.emit()
