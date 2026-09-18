"""
gui/rename_settings_widget.py

"정리 방식" 카드(gui/date_organize_screen.py, gui/city_organize_screen.py) 안,
"저장 위치" 바로 아래 들어가는 "파일명" 섹션 — gui/recovery_screen.py의
"파일명에 추가할 문구"와 같은 인라인 설정 패턴이다. 별도 팝업이 아니라 "이
방식대로 정리하기" 실행에 그대로 딸려가는 설정 — 복사/이동과 동시에 새
이름으로 저장된다(core/date_organizer.py::_run_organize의 filename_for).

기본값은 "원래 이름 유지"라 평소엔 하위 옵션이 접혀 있다가, "새 이름으로
변경"을 고르면 펼쳐진다. 두 화면(날짜별/도시별) 모두 처음부터 필요해서
DESIGN.md 원칙대로 바로 공용 위젯으로 만들었다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.theme import COLORS

DEFAULT_START = 1
DEFAULT_DIGITS = 3

# gui/recovery_screen.py::SECTION_HEADER_STYLE과 같은 값 — gui/rename_dialog.py와
# 같은 이유로 import 대신 값만 복사(그 모듈의 주석 참고, 순환 import 방지).
SECTION_HEADER_STYLE = (
    f"color: {COLORS['text']}; font-weight: 700; font-size: 13px; "
    f"border-left: 3px solid {COLORS['primary']}; padding-left: 8px; margin-top: 6px;"
)


@dataclass
class RenameSettings:
    mode: str  # "manual" | "auto"
    base_name: str  # mode="auto"일 때는 빈 문자열 — 호출부가 그룹 라벨을 대신 쓴다
    start: int
    digits: int


class RenameSettingsWidget(QWidget):
    """"파일명" 섹션. 비활성 상태(원래 이름 유지)면 settings()가 None을 돌려줘서
    호출부가 filename_for를 아예 안 만들면 된다."""

    changed = Signal()

    def __init__(self, auto_label: str, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addSpacing(6)
        filename_label = QLabel("파일명")
        filename_label.setStyleSheet(SECTION_HEADER_STYLE)
        root.addWidget(filename_label)

        keep_mode_group = QButtonGroup(self)
        self.keep_radio = QRadioButton("원래 이름 유지 (기본값)")
        self.keep_radio.setChecked(True)
        self.rename_radio = QRadioButton("새 이름으로 변경")
        keep_mode_group.addButton(self.keep_radio)
        keep_mode_group.addButton(self.rename_radio)
        root.addWidget(self.keep_radio)
        root.addWidget(self.rename_radio)

        self._detail = QWidget()
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(20, 4, 0, 0)
        detail_layout.setSpacing(6)

        input_mode_row = QHBoxLayout()
        input_mode_group = QButtonGroup(self._detail)
        self.manual_radio = QRadioButton("직접 입력")
        self.manual_radio.setChecked(True)
        self.auto_radio = QRadioButton(auto_label)
        input_mode_group.addButton(self.manual_radio)
        input_mode_group.addButton(self.auto_radio)
        input_mode_row.addWidget(self.manual_radio)
        input_mode_row.addWidget(self.auto_radio)
        input_mode_row.addStretch(1)
        detail_layout.addLayout(input_mode_row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 여행")
        detail_layout.addWidget(self.name_edit)

        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("시작 번호"))
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 99999)
        self.start_spin.setValue(DEFAULT_START)
        opts_row.addWidget(self.start_spin)
        opts_row.addSpacing(12)
        opts_row.addWidget(QLabel("자릿수"))
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(1, 6)
        self.digits_spin.setValue(DEFAULT_DIGITS)
        opts_row.addWidget(self.digits_spin)
        opts_row.addStretch(1)
        detail_layout.addLayout(opts_row)

        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        detail_layout.addWidget(self.preview_label)

        root.addWidget(self._detail)
        self._detail.setVisible(False)

        self.rename_radio.toggled.connect(self._detail.setVisible)
        self.keep_radio.toggled.connect(lambda _checked: self.changed.emit())
        self.rename_radio.toggled.connect(lambda _checked: self.changed.emit())
        self.manual_radio.toggled.connect(self._update_preview)
        self.auto_radio.toggled.connect(self._update_preview)
        self.name_edit.textChanged.connect(self._update_preview)
        self.start_spin.valueChanged.connect(self._update_preview)
        self.digits_spin.valueChanged.connect(self._update_preview)

        self._update_preview()

    def _update_preview(self, *_args) -> None:
        if self.auto_radio.isChecked():
            self.name_edit.setEnabled(False)
            base = "(그룹 이름)"
        else:
            self.name_edit.setEnabled(True)
            base = self.name_edit.text().strip() or "이름없음"
        start = self.start_spin.value()
        digits = self.digits_spin.value()
        samples = ", ".join(f"{base}_{str(start + i).zfill(digits)}.jpg" for i in range(2))
        self.preview_label.setText(f"미리보기: {samples}, ...")
        self.changed.emit()

    def is_valid(self) -> bool:
        """"새 이름으로 변경"이 꺼져 있으면 항상 유효(설정 자체가 없는 것과
        같음). 켜져 있으면 자동 입력은 항상 유효, 직접 입력은 이름이 비어있지
        않아야 한다."""
        if not self.rename_radio.isChecked():
            return True
        if self.auto_radio.isChecked():
            return True
        return bool(self.name_edit.text().strip())

    def settings(self) -> Optional[RenameSettings]:
        if not self.rename_radio.isChecked():
            return None
        mode = "auto" if self.auto_radio.isChecked() else "manual"
        return RenameSettings(
            mode=mode,
            base_name=self.name_edit.text().strip(),
            start=self.start_spin.value(),
            digits=self.digits_spin.value(),
        )
