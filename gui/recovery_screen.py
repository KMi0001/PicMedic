"""
gui/recovery_screen.py

PRD 20장 "Screen 05 — Recovery" 구현.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QSettings
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QFileDialog,
    QProgressBar,
    QDialog,
)

from core.converter import RecoveryMode, recover_batch, CONVERT_TARGET_FORMATS, DEFAULT_CONVERT_FORMAT
from gui.result_screen import SummaryChip
from gui.theme import COLORS, STATUS_COLORS
from models.file_info import FileInfo, FileStatus
from utils.file_utils import DEFAULT_SUFFIX

# 상태 카드 순서 + 라벨. NORMAL부터 심각도 순으로, "지원 안 함" 계열은 뒤에 묶는다.
STATUS_CHIP_LABELS: dict[FileStatus, str] = {
    FileStatus.NORMAL: "정상",
    FileStatus.MISMATCH: "형식 불일치",
    FileStatus.PARTIAL_CORRUPTION: "부분 손상",
    FileStatus.CORRUPTED: "손상",
    FileStatus.UNSUPPORTED: "지원 안 함",
    FileStatus.NOT_AN_IMAGE: "이미지 아님",
    FileStatus.UNKNOWN: "알 수 없음",
}

# HEADER_STYLE: 카드 안의 섹션 제목(복구 방식/저장 위치/파일명에 추가할 문구)을
# 본문 텍스트와 구분되게 강조한다 — 진한 글씨 + 왼쪽 accent bar (DESIGN.md 참고).
SECTION_HEADER_STYLE = (
    f"color: {COLORS['text']}; font-weight: 700; font-size: 13px; "
    f"border-left: 3px solid {COLORS['primary']}; padding-left: 8px; margin-top: 6px;"
)


QUALITY_PRESETS = {"고화질": 95, "보통": 85, "저용량": 65}
DEFAULT_QUALITY_PRESET = "보통"
# 이 형식들만 Pillow 저장 시 quality를 실제로 쓴다 (core/converter.py::convert_to_format 참고)
QUALITY_APPLICABLE_FORMATS = {"JPEG", "WEBP"}


def _question_icon_pixmap(accent: str, size: int = 48) -> QPixmap:
    """확인 필요 팝업 아이콘: 최근 검사 목록 아이콘(gui/home_screen.py::_status_icon_pixmap)과
    같은 스타일(색 원 + 흰색 글리프, 이모지 폰트 미사용)로 맞춘 물음표 아이콘."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(0, 0, size, size)
    painter.setFont(QFont("Segoe UI", int(size * (13 / 24) * 0.55), QFont.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "?")
    painter.end()
    return pixmap


def _confirm_dialog(parent: QWidget, message: str) -> bool:
    """취소/확인 버튼이 있는 카드형 확인 팝업. 확인을 누르면 True."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")

    layout = QHBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)

    icon_label = QLabel()
    icon_label.setPixmap(_question_icon_pixmap(COLORS["primary"]))
    layout.addWidget(icon_label, alignment=Qt.AlignTop)

    text_col = QVBoxLayout()
    msg_label = QLabel(message)
    msg_label.setWordWrap(True)
    msg_label.setFixedWidth(280)
    text_col.addWidget(msg_label)

    text_col.addSpacing(12)
    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton("확인")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    text_col.addLayout(btn_row)

    layout.addLayout(text_col)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    return dialog.exec() == QDialog.Accepted


class _ProgressDialog(QDialog):
    """복구/변환 진행 중 뜨는 모달 팝업. 배치 작업이 끝날 때까지 화면(설정/뒤로가기
    등)을 건드릴 수 없게 막는다 — PRD_MVP우선순위.md 갭 #9(진행 중 설정 잠금 필요)를
    "모든 컨트롤을 개별적으로 비활성화" 대신 모달 팝업 하나로 해결한다. 중단 기능은
    core/converter.py::recover_batch에 아직 없어(갭 #9 후속) 닫기 버튼도 없앤다 —
    끝날 때까지 기다리는 것 외에 다른 조작이 불가능함을 명확히 한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PicMedic")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(self.title_label)

        self.bar = QProgressBar()
        layout.addWidget(self.bar)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.status_label)

    def start(self, title: str):
        self.title_label.setText(title)
        self.bar.setValue(0)
        self.status_label.setText("준비 중...")

    def update_progress(self, current: int, total: int, filename: str):
        pct = int((current / total) * 100) if total else 0
        self.bar.setValue(pct)
        self.status_label.setText(f"{filename} 처리 중... ({current}/{total})")


class RecoveryWorker(QThread):
    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[RecoveryOutcome]

    def __init__(
        self,
        files: list[FileInfo],
        mode: RecoveryMode,
        output_dir: str,
        suffix: str = DEFAULT_SUFFIX,
        target_format: str = DEFAULT_CONVERT_FORMAT,
        quality: int = 90,
        parent=None,
    ):
        super().__init__(parent)
        self.files = files
        self.mode = mode
        self.output_dir = output_dir
        self.suffix = suffix
        self.target_format = target_format
        self.quality = quality

    def run(self):
        outcomes = recover_batch(
            self.files,
            self.mode,
            self.output_dir,
            progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
            suffix=self.suffix,
            target_format=self.target_format,
            quality=self.quality,
        )
        self.finished_batch.emit(outcomes)


class RecoveryScreen(QWidget):
    recovery_finished = Signal(list, str)  # list[RecoveryOutcome], output_dir
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PicMedic", "PicMedic")
        self.files: list[FileInfo] = []
        self.worker: RecoveryWorker | None = None
        self.progress_dialog = _ProgressDialog(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        outer.addWidget(back_btn, alignment=Qt.AlignLeft)

        self.title_label = QLabel("사진 복구")
        self.title_label.setObjectName("Title")
        outer.addWidget(self.title_label)

        # 선택 파일 상태 요약 — 검사 결과 화면(gui/result_screen.py)의 SummaryChip을
        # 그대로 재사용해 같은 카드형 스타일로 보여준다. 실제로 존재하는 상태만 노출한다.
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        chips_row.addStretch(1)
        self.chip_total = SummaryChip("선택 파일", COLORS["text"])
        chips_row.addWidget(self.chip_total)
        self.status_chips: dict[FileStatus, SummaryChip] = {}
        for status, label in STATUS_CHIP_LABELS.items():
            chip = SummaryChip(label, STATUS_COLORS[status.value])
            chip.setVisible(False)
            self.status_chips[status] = chip
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(14)

        self.mode_label = QLabel("복구 방식")
        self.mode_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(self.mode_label)

        self.mode_group = QButtonGroup(self)
        self.restore_radio = QRadioButton("확장자 복원")
        self.convert_radio = QRadioButton("형식 변환")
        self.convert_radio.setChecked(True)
        self.mode_group.addButton(self.restore_radio)
        self.mode_group.addButton(self.convert_radio)
        card_layout.addWidget(self.restore_radio)

        convert_row = QHBoxLayout()
        convert_row.addWidget(self.convert_radio)
        self.format_combo = QComboBox()
        self.format_combo.addItems(CONVERT_TARGET_FORMATS)
        self.format_combo.setCurrentText(DEFAULT_CONVERT_FORMAT)
        convert_row.addWidget(self.format_combo)

        self.quality_label = QLabel("화질")
        self.quality_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        convert_row.addWidget(self.quality_label)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITY_PRESETS.keys())
        self.quality_combo.setCurrentText(DEFAULT_QUALITY_PRESET)
        convert_row.addWidget(self.quality_combo)

        convert_row.addStretch(1)
        card_layout.addLayout(convert_row)

        self.restore_radio.toggled.connect(self._on_mode_changed)
        self.convert_radio.toggled.connect(self._on_mode_changed)
        self.format_combo.currentTextChanged.connect(self._on_mode_changed)
        self._on_mode_changed()

        output_label = QLabel("저장 위치")
        output_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(output_label)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_row.addWidget(self.output_edit)
        browse_btn = QPushButton("찾아보기")
        browse_btn.clicked.connect(self._browse_output)
        output_row.addWidget(browse_btn)
        card_layout.addLayout(output_row)

        suffix_label = QLabel("파일명에 추가할 문구")
        suffix_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(suffix_label)

        self.suffix_edit = QLineEdit(DEFAULT_SUFFIX)
        card_layout.addWidget(self.suffix_edit)

        keep_original_note = QLabel("원본 파일은 항상 그대로 보존되며, 복구 결과는 별도 폴더에 새 파일로 저장됩니다.")
        keep_original_note.setWordWrap(True)
        keep_original_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        card_layout.addWidget(keep_original_note)

        self.verify_check = QCheckBox("복구 후 파일 검증")
        self.verify_check.setChecked(True)
        card_layout.addWidget(self.verify_check)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        card_layout.addWidget(self.status_label)

        self.start_btn = QPushButton("Medic!")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start_recovery)
        card_layout.addWidget(self.start_btn)

        outer.addWidget(card)

    # --- 외부에서 호출 --------------------------------------------------

    def set_files(self, files: list[FileInfo], preselected_mode: RecoveryMode | None = None):
        self.files = files
        self.chip_total.set_value(len(files))
        status_counts = Counter(f.status for f in files)
        for status, chip in self.status_chips.items():
            count = status_counts.get(status, 0)
            chip.set_value(count)
            chip.setVisible(count > 0)

        # 확장자와 실제 형식이 다른 파일이 하나도 없으면(예: 정상 파일만 골라서
        # "변환"하러 온 경우) "확장자 복원"은 애초에 할 게 없다. 이 경우 선택지가
        # "형식 변환" 하나뿐이니 라디오 버튼 자체를 없애고, 곧바로 변환 옵션(형식/화질)만
        # 보여준다.
        can_restore = any(f.is_mismatched for f in files)
        self._convert_only = not can_restore

        self.restore_radio.setVisible(can_restore)
        self.convert_radio.setVisible(can_restore)
        self.mode_label.setText("복구 방식" if can_restore else "확장자 변환")
        self.verify_check.setText("복구 후 파일 검증" if can_restore else "변환 후 파일 검증")

        # 검사 결과 화면의 "Medic!"(일괄 복구)은 preselected_mode 없이 들어온다. 복원할 게
        # 있으면(can_restore) 기본값은 "확장자 복원"이어야 한다 — 안 그러면 안전한 옵션인
        # "확장자 복원"으로 명시적으로 바꾸지 않는 한 정상 파일까지 매번 재인코딩(형식 변환)
        # 당하게 된다. detail_screen에서 "형식 변환" 버튼을 눌러 들어온 경우(preselected_mode
        # == CONVERT)에는 사용자가 변환을 원한 게 명확하므로 그대로 존중한다.
        if can_restore and preselected_mode != RecoveryMode.CONVERT:
            self.restore_radio.setChecked(True)
        else:
            self.convert_radio.setChecked(True)

        self.format_combo.setCurrentText(DEFAULT_CONVERT_FORMAT)

        default_dir = self.settings.value("last_output_dir", "")
        if not default_dir and files:
            default_dir = str(Path(files[0].path).parent / "Recovered")
        self.output_edit.setText(default_dir)
        self.suffix_edit.setText(DEFAULT_SUFFIX)

        self.status_label.setText("")
        self.start_btn.setEnabled(True)

        self._on_mode_changed()  # radio 상태가 이전과 같아 toggled가 안 울려도 제목/화질 표시는 갱신되게

    # --- 내부 로직 -----------------------------------------------------

    def _on_mode_changed(self):
        is_convert = self.convert_radio.isChecked()
        self.format_combo.setEnabled(is_convert)
        self.title_label.setText("사진 변환" if is_convert else "사진 복구")

        # PNG/GIF/BMP는 quality를 쓰지 않으므로(core/converter.py 참고) 화질 선택 자체가
        # 의미 없다 — 비활성화가 아니라 아예 숨긴다.
        quality_applicable = is_convert and self.format_combo.currentText() in QUALITY_APPLICABLE_FORMATS
        self.quality_label.setVisible(quality_applicable)
        self.quality_combo.setVisible(quality_applicable)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 위치 선택")
        if folder:
            self.output_edit.setText(folder)

    def _start_recovery(self):
        if not self.files:
            return
        output_dir = self.output_edit.text().strip()
        if not output_dir:
            self.status_label.setText("저장 위치를 입력해주세요.")
            return

        self.settings.setValue("last_output_dir", output_dir)
        mode = RecoveryMode.RESTORE_EXTENSION if self.restore_radio.isChecked() else RecoveryMode.CONVERT
        suffix = self.suffix_edit.text().strip() or DEFAULT_SUFFIX
        target_format = self.format_combo.currentText()
        quality = QUALITY_PRESETS[self.quality_combo.currentText()]

        # 확장자 복원 모드는 이미 정상인 파일에는 복원할 내용이 없어 자동으로 건너뛴다
        # (core/converter.py::recover_file, PRD_MVP우선순위.md '갭 #11'). 시작 직전에 팝업으로
        # 미리 알려준다 — 형식 변환 모드는 정상 파일에도 쓸 수 있는 의도된 기능이라 안내하지 않는다.
        if mode == RecoveryMode.RESTORE_EXTENSION:
            normal_count = sum(1 for f in self.files if f.status == FileStatus.NORMAL)
            if normal_count:
                confirmed = _confirm_dialog(
                    self,
                    f"선택한 파일 중 {normal_count}개는 이미 정상 파일이라 복원할 내용이 없어 건너뜁니다.\n계속 진행할까요?",
                )
                if not confirmed:
                    return

        self.start_btn.setEnabled(False)
        self.status_label.setText("")

        self.worker = RecoveryWorker(
            self.files, mode, output_dir, suffix=suffix, target_format=target_format, quality=quality
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_batch.connect(lambda outcomes: self._on_finished(outcomes, output_dir))
        self.worker.start()

        # 진행 중에는 모달 팝업만 응답하게 만들어, 배치 작업 중 설정을 바꾸거나 뒤로 가서
        # 화면이 바뀌는 문제(PRD_MVP우선순위.md 갭 #9)를 막는다. exec()는 중첩 이벤트
        # 루프라 워커 스레드의 progress/finished_batch 시그널은 계속 정상적으로 처리된다.
        title = "사진 변환 진행 중" if mode == RecoveryMode.CONVERT else "사진 복구 진행 중"
        self.progress_dialog.start(title)
        self.progress_dialog.exec()

    def _on_progress(self, current: int, total: int, filename: str):
        self.progress_dialog.update_progress(current, total, filename)

    def _on_finished(self, outcomes, output_dir: str):
        self.progress_dialog.accept()
        self.start_btn.setEnabled(True)
        self.recovery_finished.emit(outcomes, output_dir)
