"""
gui/recovery_screen.py

PRD 20장 "Screen 05 — Recovery" 구현.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QSettings, QPointF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen
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
    QSizePolicy,
)

from core.converter import RecoveryMode, recover_batch, CONVERT_TARGET_FORMATS, DEFAULT_CONVERT_FORMAT
from gui.common_dialogs import confirm_dialog as _confirm_dialog, ProgressDialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS, STATUS_COLORS
from models.file_info import FileInfo, FileStatus
from utils import trash
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


def _convert_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목("사진 복구"/"사진 변환") 옆에 붙는 아이콘 — 서로 반대 방향을
    가리키는 화살표 두 개로 "다른 형태로 바꾼다"는 의미(복원/변환 둘 다에 해당).
    검사 결과 화면의 돋보기 아이콘([gui/result_screen.py](gui/result_screen.py)
    `_search_icon_pixmap`)과 같은 아웃라인 스트로크 스타일."""
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

    def p(x, y):
        return QPointF(x * scale, y * scale)

    # 위: 오른쪽을 가리키는 화살표
    painter.drawLine(p(4, 8), p(17, 8))
    painter.drawLine(p(13, 4), p(17, 8))
    painter.drawLine(p(13, 12), p(17, 8))
    # 아래: 왼쪽을 가리키는 화살표
    painter.drawLine(p(20, 16), p(7, 16))
    painter.drawLine(p(11, 12), p(7, 16))
    painter.drawLine(p(11, 20), p(7, 16))

    painter.end()
    return pixmap


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
        replace_original: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.files = files
        self.mode = mode
        self.output_dir = output_dir
        self.suffix = suffix
        self.target_format = target_format
        self.quality = quality
        self.replace_original = replace_original
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        outcomes = recover_batch(
            self.files,
            self.mode,
            self.output_dir,
            progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
            suffix=self.suffix,
            target_format=self.target_format,
            quality=self.quality,
            should_cancel=lambda: self._cancel_requested,
            replace_original=self.replace_original,
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
        self._cancel_requested = False
        self.progress_dialog = ProgressDialog(self)
        self.progress_dialog.cancel_requested.connect(self._on_cancel_requested)

        # 화면 전체를 쓰는 큰 창에서 설정 카드가 창 끝까지 늘어나면 텅 빈 공간이
        # 남아 허전해 보인다(gui/organize_hub_screen.py에서 고친 것과 같은 문제) —
        # 내용 폭을 한 번 고정(900px)하고 가운데 정렬한다.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(900)
        # stretch factor 0인 위젯은 양옆 addStretch(1)에 밀려 sizeHint만큼만
        # 차지하고 절대 안 커진다 — setMaximumWidth는 상한만 정할 뿐, 실제로
        # 그 상한까지 채우는 힘은 Expanding 정책 + 양옆보다 훨씬 큰 stretch
        # factor가 있어야 생긴다(2026-09-08, 사용자 리포트 — "정리 화면이
        # 이상하게 좁다", gui/duplicate_screen.py와 같은 원인/수정 — 이
        # 화면엔 그때 빠뜨렸다가 뒤늦게 발견함, 2026-09-09).
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(content, 100)
        root.addStretch(1)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        # 검사 결과 화면(gui/result_screen.py)과 같은 레이아웃 — 제목은 왼쪽,
        # 액션 버튼("← 뒤로")은 같은 줄 오른쪽 끝.
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_convert_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        self.title_label = QLabel("사진 복구")
        self.title_label.setObjectName("Title")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        # 선택 파일 상태 요약 — 검사 결과 화면(gui/result_screen.py)의 SummaryChip을
        # 그대로 재사용해 같은 카드형 스타일로 보여준다. 실제로 존재하는 상태만 노출한다.
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
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

        # 2026-09-10, 사용자 요청 — "저장 위치 지정(원본 보존)"과 "원본 삭제(대체)"는
        # 서로 배타적인 선택지라 체크박스+비활성화 대신 라디오 버튼 두 개로 고르게
        # 한다("저장 위치"는 원본 보존을 골랐을 때만 의미가 있어서 그 아래 둠).
        # 기본은 항상 "원본 보존"이고, "원본 삭제"를 골랐을 때만 원본을 그 폴더의
        # 임시휴지통으로 옮기고 결과물이 원본이 있던 자리를 대신한다
        # (core/converter.py::_recover_file_replacing_original).
        self.output_mode_label = QLabel("저장 방식")
        self.output_mode_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(self.output_mode_label)

        self.output_mode_group = QButtonGroup(self)
        self.keep_original_radio = QRadioButton("원본 보존 — 별도 폴더에 새 파일로 저장 (기본값)")
        self.keep_original_radio.setChecked(True)
        self.replace_original_radio = QRadioButton(
            "원본 삭제 — 원본을 임시휴지통으로 옮기고, 결과물이 그 자리를 대신하게 하기"
        )
        self.output_mode_group.addButton(self.keep_original_radio)
        self.output_mode_group.addButton(self.replace_original_radio)
        card_layout.addWidget(self.keep_original_radio)
        card_layout.addWidget(self.replace_original_radio)

        self.output_label = QLabel("저장 위치")
        self.output_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(self.output_label)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_row.addWidget(self.output_edit)
        self.browse_btn = QPushButton("찾아보기")
        self.browse_btn.clicked.connect(self._browse_output)
        output_row.addWidget(self.browse_btn)
        card_layout.addLayout(output_row)

        self.suffix_label = QLabel("파일명에 추가할 문구")
        self.suffix_label.setStyleSheet(SECTION_HEADER_STYLE)
        card_layout.addWidget(self.suffix_label)

        self.suffix_edit = QLineEdit(DEFAULT_SUFFIX)
        card_layout.addWidget(self.suffix_edit)

        self.keep_original_note = QLabel(
            "원본 파일은 항상 그대로 보존되며, 복구 결과는 별도 폴더에 새 파일로 저장됩니다."
        )
        self.keep_original_note.setWordWrap(True)
        self.keep_original_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        card_layout.addWidget(self.keep_original_note)

        self.keep_original_radio.toggled.connect(self._on_output_mode_changed)
        self.replace_original_radio.toggled.connect(self._on_output_mode_changed)
        self._on_output_mode_changed()

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
        # 매번 안전한 기본값("원본 보존")에서 시작 — 이전 파일들에서 "원본 삭제"를
        # 골라뒀던 채로 이번 파일들에 실수로 적용되는 일이 없게 한다.
        self.keep_original_radio.setChecked(True)

        default_dir = self.settings.value("last_output_dir", "")
        if not default_dir and files:
            default_dir = str(Path(files[0].path).parent / "Recovered")
        self.output_edit.setText(default_dir)
        self.suffix_edit.setText(DEFAULT_SUFFIX)

        self.status_label.setText("")
        self.start_btn.setEnabled(True)

        self._on_mode_changed()  # radio 상태가 이전과 같아 toggled가 안 울려도 제목/화질 표시는 갱신되게

    # --- 내부 로직 -----------------------------------------------------

    def _on_output_mode_changed(self):
        # "원본 삭제"를 고르면 "저장 위치"/"파일명에 추가할 문구"는 안 쓰인다 —
        # 결과가 항상 원본이 있던 그 폴더에, 원본 이름 그대로(확장자만 결과에
        # 맞게) 저장되기 때문(core/converter.py::_recover_file_replacing_original).
        # 회색으로 비활성화만 하면 "왜 안 써도 되는 칸이 계속 보이지?" 헷갈릴 수
        # 있어 아예 숨긴다(2026-09-10, 사용자 요청) — 값 자체는 지우지 않으니
        # 다시 "원본 보존"으로 돌아가면 이전에 입력해둔 값이 그대로 남는다.
        checked = self.replace_original_radio.isChecked()
        self.output_label.setVisible(not checked)
        self.output_edit.setVisible(not checked)
        self.browse_btn.setVisible(not checked)
        self.suffix_label.setVisible(not checked)
        self.suffix_edit.setVisible(not checked)
        if checked:
            self.keep_original_note.setText(
                "원본은 그 폴더의 \"임시휴지통\"으로 옮겨지고, 복구 결과가 원본이 있던 자리를 대신합니다. "
                "필요하면 임시휴지통에서 원본을 다시 꺼내올 수 있어요."
            )
        else:
            self.keep_original_note.setText(
                "원본 파일은 항상 그대로 보존되며, 복구 결과는 별도 폴더에 새 파일로 저장됩니다."
            )

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
        replace_original = self.replace_original_radio.isChecked()
        # replace_original이면 저장 위치칸은 안 쓰인다(파일마다 원본이 있던
        # 폴더로 감) — 빈 문자열로 비워서 아래 결과 화면에 옛날 입력값이
        # "저장 위치"인 것처럼 잘못 보이지 않게 한다.
        output_dir = "" if replace_original else self.output_edit.text().strip()
        if not replace_original and not output_dir:
            self.status_label.setText("저장 위치를 입력해주세요.")
            return
        if not replace_original:
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
        self._cancel_requested = False

        self.worker = RecoveryWorker(
            self.files,
            mode,
            output_dir,
            suffix=suffix,
            target_format=target_format,
            quality=quality,
            replace_original=replace_original,
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

    def _on_cancel_requested(self):
        if self.worker:
            self.worker.cancel()
        self._cancel_requested = True

    def _on_finished(self, outcomes, output_dir: str):
        self.progress_dialog.accept()
        self.start_btn.setEnabled(True)

        if self._cancel_requested:
            keep = _confirm_dialog(
                self,
                "복구된 파일을 유지하시겠습니까?",
                confirm_text="유지",
                cancel_text="삭제",
            )
            if not keep:
                self._delete_outputs(outcomes)
                return  # 결과 화면으로 넘어가지 않고 설정 화면에 그대로 남는다

        self.recovery_finished.emit(outcomes, output_dir)

    def _delete_outputs(self, outcomes):
        # 보통은 core/converter.py가 항상 별도 폴더에만 쓰므로 여기서 지우는 건 취소
        # 시점까지 만들어진 결과물 사본뿐 — 원본 파일은 영향받지 않는다. 개별 파일
        # 삭제 실패(권한 등)는 배치 취소 자체를 막을 이유가 없어 조용히 넘어간다.
        # "원본 삭제" 옵션이 켜져 있던 항목(replaced_original_trash_path가 있음)은
        # 원본이 이미 임시휴지통으로 옮겨간 상태라, 결과물만 지우면 그 폴더에서
        # 사진이 통째로 사라져 버린다 — 그런 항목은 결과물을 지우면서 원본도
        # 같이 제자리로 되돌린다(취소=완전히 되돌리기).
        for outcome in outcomes:
            if outcome.success and outcome.output_path:
                try:
                    Path(outcome.output_path).unlink(missing_ok=True)
                except OSError:
                    pass
            if outcome.replaced_original_trash_path:
                try:
                    trash.restore_from_trash(Path(outcome.replaced_original_trash_path))
                except (ValueError, OSError):
                    pass  # 되돌리기 실패해도 원본 자체는 임시휴지통에 안전하게 남아있다
