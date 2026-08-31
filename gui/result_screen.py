"""
gui/result_screen.py

PRD 18장 "Screen 03 — Scan Result" 구현.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRect, QItemSelectionModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QFrame,
)

from gui.theme import COLORS, STATUS_COLORS, STATUS_DOT
from models.file_info import FileStatus, RecoveryPossibility
from models.scan_result import ScanResult
from utils.file_utils import format_file_size

FILTER_OPTIONS = [
    "전체",
    "정상",
    "형식 불일치",
    "부분 손상",
    "손상",
    "복구 완료",
    "복구 가능한 파일만",
    "지원안함/오류",
]


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
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedWidth(CHIP_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.value_label = QLabel("0")
        self.value_label.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color};")
        name_label = QLabel(label)
        name_label.setWordWrap(True)
        name_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        layout.addWidget(self.value_label)
        layout.addWidget(name_label)

    def set_value(self, value: int):
        self.value_label.setText(f"{value:,}")


class ResultScreen(QWidget):
    file_selected = Signal(object)       # FileInfo
    recovery_requested = Signal(list)    # list[FileInfo]
    rescan_requested = Signal()
    resume_requested = Signal()          # 중단된 검사를 나머지 파일부터 이어서 진행

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: ScanResult | None = None
        self._current_files: list = []
        self._syncing = False  # 체크박스<->행 선택 동기화 재진입 방지

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(14)

        header_row = QHBoxLayout()
        title = QLabel("검사 결과")
        title.setObjectName("Title")
        header_row.addWidget(title)
        header_row.addStretch(1)
        rescan_btn = QPushButton("다시 검사")
        rescan_btn.clicked.connect(self.rescan_requested.emit)
        header_row.addWidget(rescan_btn)
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

        chips_row = QHBoxLayout()
        self.chip_total = SummaryChip("총 파일", COLORS["text"])
        self.chip_normal = SummaryChip("정상", STATUS_COLORS["정상"])
        self.chip_mismatch = SummaryChip("형식 불일치", STATUS_COLORS["형식_불일치"])
        self.chip_partial = SummaryChip("부분 손상", STATUS_COLORS["부분_손상"])
        self.chip_corrupted = SummaryChip("손상", STATUS_COLORS["손상"])
        self.chip_recovered = SummaryChip("복구 완료", STATUS_COLORS["복구_완료"])
        for chip in (
            self.chip_total,
            self.chip_normal,
            self.chip_mismatch,
            self.chip_partial,
            self.chip_corrupted,
            self.chip_recovered,
        ):
            chips_row.addWidget(chip)
        outer.addLayout(chips_row)

        action_row = QHBoxLayout()
        self.recoverable_btn = QPushButton("복구 가능한 파일 보기")
        self.recoverable_btn.clicked.connect(self._show_recoverable_only)
        action_row.addWidget(self.recoverable_btn)

        action_row.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("파일명·확장자·실제 형식 검색")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self._apply_filters)
        action_row.addWidget(self.search_box)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(FILTER_OPTIONS)
        self.filter_combo.currentIndexChanged.connect(self._apply_filters)
        action_row.addWidget(self.filter_combo)
        outer.addLayout(action_row)

        self.table = QTableWidget(0, 7)
        self._header = CheckAllHeaderView(self.table)
        self._header.toggled.connect(self._on_header_toggled)
        self.table.setHorizontalHeader(self._header)
        self.table.setHorizontalHeaderLabels(["", "상태", "파일명", "실제 형식", "확장자", "크기", "수정일"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        outer.addWidget(self.table, stretch=1)

        bottom_row = QHBoxLayout()
        self.selection_label = QLabel("선택된 파일 없음")
        self.selection_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        bottom_row.addWidget(self.selection_label)
        bottom_row.addStretch(1)
        self.recover_selected_btn = QPushButton("Medic!")
        self.recover_selected_btn.setObjectName("Primary")
        self.recover_selected_btn.setEnabled(False)
        self.recover_selected_btn.clicked.connect(self._on_recover_selected)
        bottom_row.addWidget(self.recover_selected_btn)
        outer.addLayout(bottom_row)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # --- 외부에서 호출 --------------------------------------------------

    def set_result(
        self,
        result: ScanResult,
        cancelled: bool = False,
        planned_total: int | None = None,
        remaining_paths: list | None = None,
    ):
        self.result = result
        self.chip_total.set_value(result.total)
        self.chip_normal.set_value(result.normal)
        self.chip_mismatch.set_value(result.mismatch)
        self.chip_partial.set_value(result.partial_corruption)
        self.chip_corrupted.set_value(result.corrupted)
        self.chip_recovered.set_value(result.recovered)

        if cancelled:
            planned = planned_total or result.total
            self.cancelled_banner.setText(
                f"⚠ 검사가 중단되어 {result.total:,} / {planned:,}개 파일까지만 검사되었습니다."
            )
            self.resume_btn.setVisible(bool(remaining_paths))
            self.cancelled_banner_frame.show()
        else:
            self.cancelled_banner_frame.hide()

        self.filter_combo.setCurrentIndex(0)
        self.search_box.clear()
        self._apply_filters()

    def refresh_current_result(self):
        """복구 후 파일 상태가 갱신됐을 때 요약/테이블을 다시 그린다."""
        if self.result:
            self.chip_normal.set_value(self.result.normal)
            self.chip_mismatch.set_value(self.result.mismatch)
            self.chip_partial.set_value(self.result.partial_corruption)
            self.chip_corrupted.set_value(self.result.corrupted)
            self.chip_recovered.set_value(self.result.recovered)
            self._apply_filters()

    # --- 내부 로직 -----------------------------------------------------

    def _show_recoverable_only(self):
        idx = FILTER_OPTIONS.index("복구 가능한 파일만")
        self.filter_combo.setCurrentIndex(idx)

    def _apply_filters(self):
        if not self.result:
            return

        filter_choice = self.filter_combo.currentText()
        query = self.search_box.text().strip().lower()

        status_map = {
            "정상": FileStatus.NORMAL,
            "형식 불일치": FileStatus.MISMATCH,
            "부분 손상": FileStatus.PARTIAL_CORRUPTION,
            "손상": FileStatus.CORRUPTED,
            "복구 완료": FileStatus.RECOVERED,
        }

        if filter_choice == "전체":
            files = list(self.result.files)
        elif filter_choice == "복구 가능한 파일만":
            files = self.result.recoverable_files()
        elif filter_choice == "지원안함/오류":
            files = [
                f
                for f in self.result.files
                if f.status in (FileStatus.UNSUPPORTED, FileStatus.NOT_AN_IMAGE, FileStatus.UNKNOWN)
            ]
        else:
            files = self.result.by_status(status_map[filter_choice])

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
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)  # 채우는 동안 정렬되면 행-데이터가 뒤섞일 수 있음
        self.table.setUpdatesEnabled(False)  # 수만 행일 때 매 setItem마다 다시 그리지 않도록
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(files))
        for row, info in enumerate(files):
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
            format_item = QTableWidgetItem(info.detected_format or "-")
            ext_item = QTableWidgetItem(info.extension)

            size_item = _NumericSortItem(format_file_size(info.file_size))
            size_item.setData(Qt.UserRole, info.file_size)

            mtime = _safe_mtime(info.path)
            date_item = _NumericSortItem(_format_mtime(mtime))
            date_item.setData(Qt.UserRole, mtime if mtime is not None else -1)

            if not_recoverable:
                for cell in (status_item, name_item, format_item, ext_item, size_item, date_item):
                    cell.setToolTip("복구할 수 없는 파일입니다.")

            self.table.setItem(row, 0, check_item)
            self.table.setItem(row, 1, status_item)
            self.table.setItem(row, 2, name_item)
            self.table.setItem(row, 3, format_item)
            self.table.setItem(row, 4, ext_item)
            self.table.setItem(row, 5, size_item)
            self.table.setItem(row, 6, date_item)

        self.table.blockSignals(False)
        self.table.setSortingEnabled(was_sorting)
        self.table.setUpdatesEnabled(True)
        self._update_selection_label()

    def _on_row_double_clicked(self, index):
        if index.column() == 0:
            return  # 체크박스 칸 더블클릭은 상세 화면으로 넘기지 않는다
        item = self.table.item(index.row(), 0)
        if item:
            info = item.data(Qt.UserRole)
            self.file_selected.emit(info)

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
        self.recover_selected_btn.setEnabled(len(selected) > 0)
        self._header.set_checked(total_rows > 0 and len(selected) == total_rows)

    def _on_recover_selected(self):
        selected = self._selected_files()
        if selected:
            self.recovery_requested.emit(selected)


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
