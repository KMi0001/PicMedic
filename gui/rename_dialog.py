"""
gui/rename_dialog.py

"이름 일괄변경" — 검사 결과 화면(여러 파일 선택 후 버튼)과 홈 화면("이름
일괄변환" 카드) 두 진입점이 공유하는 팝업. 선택된 파일들의 이름을 "기본이름_순번"
규칙으로 한 번에 바꾼다(원래 있던 폴더 그 자리에서 rename — core/renamer.py).

gui/convert_dialog.py::run_convert와 같은 패턴: 홈 화면 진입은 검사 없이 곧장
core/scanner.py::list_image_files로 폴더를 가볍게 펼친 뒤 이 팝업을 연다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.renamer import rename_batch
from core.scanner import list_image_files
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.theme import COLORS
from models.file_info import FileInfo
from models.scan_result import ScanResult

DEFAULT_START = 1
DEFAULT_DIGITS = 3

# gui/recovery_screen.py::SECTION_HEADER_STYLE과 같은 값 — 여기서 그 모듈을
# import하면 gui/result_screen.py(이 파일을 import함) <-> gui/recovery_screen.py
# (gui/result_screen.py를 import함) 순환 import가 생겨서 값만 그대로 복사해 둔다.
SECTION_HEADER_STYLE = (
    f"color: {COLORS['text']}; font-weight: 700; font-size: 13px; "
    f"border-left: 3px solid {COLORS['primary']}; padding-left: 8px; margin-top: 6px;"
)


def _common_date_label(files: list[FileInfo]) -> str | None:
    """files가 전부 같은 촬영월(EXIF)을 공유하면 "자동 입력"에 쓸 라벨을
    돌려준다 — models/scan_result.py::date_groups()와 같은 "YYYY년 M월" 형식.
    하나라도 촬영일을 모르거나(list_image_files로 가볍게 연 경우 전부 이쪽)
    서로 다른 달이면 None(자동 입력 비활성화)."""
    if not files or any(f.captured_at is None for f in files):
        return None
    months = {(f.captured_at.year, f.captured_at.month) for f in files}
    if len(months) != 1:
        return None
    year, month = next(iter(months))
    return f"{year}년 {month}월"


class RenameDialog(QDialog):
    """이름 일괄변경 설정 + 미리보기 팝업. DESIGN.md 팝업 패턴(카드형,
    WindowModal)을 따른다. accept() 시점엔 아직 아무 파일도 안 바뀐 상태 —
    실제 rename은 호출부(open_rename_dialog)가 진행률 팝업과 함께 실행한다."""

    def __init__(self, parent: QWidget, files: list[FileInfo]):
        super().__init__(parent)
        self.setWindowTitle("PicMedic — 이름 일괄변경")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(440)
        self._files = files
        self._common_group = _common_date_label(files)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("이름 일괄변경")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(f"선택한 {len(files)}개 파일의 이름을 한 번에 바꿔요. 원본 파일 자체의 이름이 바뀝니다.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        root.addWidget(hint)

        mode_row = QHBoxLayout()
        self.radio_manual = QRadioButton("이름 직접 입력")
        self.radio_auto = QRadioButton("자동 입력 (촬영월 기준)")
        self.radio_manual.setChecked(True)
        if self._common_group is None:
            self.radio_auto.setEnabled(False)
            self.radio_auto.setToolTip("선택한 파일들이 같은 촬영월을 공유하지 않아 자동 입력을 쓸 수 없습니다")
        mode_row.addWidget(self.radio_manual)
        mode_row.addWidget(self.radio_auto)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        name_label = QLabel("이름")
        name_label.setStyleSheet(SECTION_HEADER_STYLE)
        root.addWidget(name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 여행")
        root.addWidget(self.name_edit)

        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("시작 번호"))
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 99999)
        self.start_spin.setValue(DEFAULT_START)
        opts_row.addWidget(self.start_spin)
        opts_row.addSpacing(16)
        opts_row.addWidget(QLabel("자릿수"))
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(1, 6)
        self.digits_spin.setValue(DEFAULT_DIGITS)
        opts_row.addWidget(self.digits_spin)
        opts_row.addStretch(1)
        root.addLayout(opts_row)

        preview_label = QLabel(f"미리보기 ({len(files)}개)")
        preview_label.setStyleSheet(SECTION_HEADER_STYLE)
        root.addWidget(preview_label)

        self.preview_grid = QGridLayout()
        self.preview_grid.setSpacing(4)
        root.addLayout(self.preview_grid)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton("변경 실행")
        self.confirm_btn.setObjectName("Primary")
        self.confirm_btn.setDefault(True)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        root.addLayout(btn_row)

        self.radio_manual.toggled.connect(self._on_mode_changed)
        self.name_edit.textChanged.connect(self._update_preview)
        self.start_spin.valueChanged.connect(self._update_preview)
        self.digits_spin.valueChanged.connect(self._update_preview)

        self._on_mode_changed()

    def base_name(self) -> str:
        return self.name_edit.text().strip()

    def start(self) -> int:
        return self.start_spin.value()

    def digits(self) -> int:
        return self.digits_spin.value()

    def _on_mode_changed(self) -> None:
        manual = self.radio_manual.isChecked()
        if not manual and self._common_group:
            # setText가 textChanged -> _update_preview를 이미 트리거하므로, 아래
            # 명시적 호출과 중복되지 않도록 잠깐 신호를 막는다.
            self.name_edit.blockSignals(True)
            self.name_edit.setText(self._common_group)
            self.name_edit.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        base = self.base_name() or "이름없음"
        start = self.start()
        digits = self.digits()
        self.confirm_btn.setEnabled(bool(self.base_name()))

        for row, info in enumerate(self._files):
            ext = Path(info.filename).suffix
            number = str(start + row).zfill(digits)
            new_name = f"{base}_{number}{ext}"

            old_label = QLabel(info.filename)
            old_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            arrow_label = QLabel("→")
            arrow_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
            new_label = QLabel(new_name)
            new_label.setStyleSheet("font-weight: 600;")

            self.preview_grid.addWidget(old_label, row, 0)
            self.preview_grid.addWidget(arrow_label, row, 1)
            self.preview_grid.addWidget(new_label, row, 2)


class _RenameWorker(QThread):
    """gui/scan_session_workers.py::_OrganizeWorker와 같은 패턴 — core/renamer.py::
    rename_batch를 별도 스레드에서 돌린다(파일이 많으면 디스크 I/O로 시간이 걸림)."""

    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[core.renamer.RenameOutcome]
    failed = Signal(str)

    def __init__(self, files: list[FileInfo], filename_for, parent=None):
        super().__init__(parent)
        self._files = files
        self._filename_for = filename_for
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            outcomes = rename_batch(
                self._files,
                self._filename_for,
                progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.finished_batch.emit(outcomes)


class _ListImagesWorker(QThread):
    """gui/convert_dialog.py::_ListImagesWorker와 같은 패턴 — 홈 화면 진입(검사 없이
    곧장 열기)에서 폴더를 사진 파일로 펼치는 동안 쓰는 워커."""

    finished_listing = Signal(object)  # ScanResult

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        result = list_image_files(self._paths, should_cancel=lambda: self._cancel_requested)
        self.finished_listing.emit(result)


def open_rename_dialog(parent: QWidget, files: list[FileInfo]) -> None:
    """이미 FileInfo 목록을 가지고 있는 호출부(검사 결과 화면의 선택 항목)가
    바로 쓰는 진입점 — 폴더 펼치기 없이 곧장 이름변경 팝업을 연다."""
    if not files:
        return

    dialog = RenameDialog(parent, files)
    if dialog.exec() != QDialog.Accepted:
        return

    base = dialog.base_name()
    start = dialog.start()
    digits = dialog.digits()

    def filename_for(info: FileInfo, index: int) -> str:
        ext = Path(info.filename).suffix
        number = str(start + index).zfill(digits)
        return f"{base}_{number}{ext}"

    progress_dialog = ProgressDialog(parent)
    worker = _RenameWorker(files, filename_for, parent)

    def on_finished(outcomes):
        progress_dialog.accept()
        worker.wait()
        _show_rename_result(parent, outcomes)

    def on_failed(message: str):
        progress_dialog.accept()
        worker.wait()
        info_dialog(parent, f"이름을 바꾸는 중 예상하지 못한 오류가 발생했습니다.\n\n{message}")

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(lambda cur, total, name: progress_dialog.update_progress(cur, total, name))
    worker.finished_batch.connect(on_finished)
    worker.failed.connect(on_failed)

    progress_dialog.start("이름 바꾸는 중")
    worker.start()
    progress_dialog.exec()


def _show_rename_result(parent: QWidget, outcomes) -> None:
    succeeded = [o for o in outcomes if o.success]
    failed = [o for o in outcomes if not o.success]

    lines = [f"{len(succeeded)}개 이름을 바꿨습니다."]
    if failed:
        lines.append(f"{len(failed)}개는 실패했습니다:")
        lines.extend(f"{o.original.filename} ({o.error_message})" for o in failed[:5])

    for outcome in succeeded:
        new_path = Path(outcome.new_path)
        outcome.original.path = str(new_path)
        outcome.original.filename = new_path.name

    info_dialog(parent, "\n".join(lines))


def run_rename(parent: QWidget, paths: list[str]) -> None:
    """홈 화면 "이름 일괄변환" 카드 진입점 — 검사 없이 paths(파일/폴더 혼합
    가능)를 사진 파일로 펼친 뒤 곧장 이름변경 팝업을 연다."""
    progress_dialog = ProgressDialog(parent)
    worker = _ListImagesWorker(paths, parent)

    def on_finished(result: ScanResult):
        progress_dialog.accept()
        worker.wait()
        files = list(result.files)
        if not files:
            info_dialog(parent, "선택한 위치에서 사진 파일을 찾지 못했어요.")
            return
        open_rename_dialog(parent, files)

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.finished_listing.connect(on_finished)

    progress_dialog.start("사진 목록을 모으는 중")
    progress_dialog.bar.setRange(0, 0)
    progress_dialog.status_label.setText("폴더를 훑어보는 중...")
    worker.start()
    progress_dialog.exec()
