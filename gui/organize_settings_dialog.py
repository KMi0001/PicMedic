"""
gui/organize_settings_dialog.py

"정리하기" 팝업 — 정리 방식(복사/이동) + 파일명(gui/rename_settings_widget.py) +
저장 위치를 한 팝업에 모은다. gui/date_organize_screen.py·city_organize_screen.py·
category_finder_screen.py 셋 다 쓰는 공용 컴포넌트.

원래는 이 설정 전부(정리 방식/파일명/저장 위치)가 화면 하단 카드에 그대로
펼쳐져 있었는데, "파일명" 섹션이 추가되면서 카드가 길어져 그룹 목록 영역이
좁아진다는 피드백(2026-09-18)으로 팝업으로 옮겼다 — 화면엔 목록 + "정리하기"
버튼만 남는다.

호출부(각 화면)가 한 번만 만들어서 계속 재사용한다 — 매번 새로 만들면 이전에
골라둔 값(정리 방식/이름 규칙)이 팝업을 열 때마다 초기화된다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from gui.rename_settings_widget import RenameSettingsWidget, SECTION_HEADER_STYLE
from gui.theme import COLORS


class OrganizeSettingsDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, auto_label: str, output_root: str = "", mode_note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(420)
        self._output_root = output_root

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        mode_label = QLabel("정리 방식")
        mode_label.setStyleSheet(SECTION_HEADER_STYLE)
        layout.addWidget(mode_label)
        if mode_note:
            note_label = QLabel(mode_note)
            note_label.setWordWrap(True)
            note_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
            layout.addWidget(note_label)
        mode_group = QButtonGroup(self)
        self.copy_radio = QRadioButton("복사 (원본은 그대로 두고 새 폴더에 사본 생성 — 기본값)")
        self.copy_radio.setChecked(True)
        mode_group.addButton(self.copy_radio)
        layout.addWidget(self.copy_radio)
        self.move_radio = QRadioButton("이동 (원본이 새 폴더로 옮겨지고 원래 위치엔 안 남음)")
        self.move_radio.setStyleSheet(f"color: {COLORS['warning']};")
        mode_group.addButton(self.move_radio)
        layout.addWidget(self.move_radio)

        layout.addSpacing(8)
        filename_label = QLabel("파일명")
        filename_label.setStyleSheet(SECTION_HEADER_STYLE)
        layout.addWidget(filename_label)
        self.rename_widget = RenameSettingsWidget(auto_label=auto_label)
        self.rename_widget.changed.connect(self._update_confirm_enabled)
        layout.addWidget(self.rename_widget)

        layout.addSpacing(8)
        output_label = QLabel("저장 위치")
        output_label.setStyleSheet(SECTION_HEADER_STYLE)
        layout.addWidget(output_label)
        output_row = QHBoxLayout()
        change_btn = QPushButton("변경")
        change_btn.clicked.connect(self._on_change_output_clicked)
        output_row.addWidget(change_btn)
        # 저장 위치는 길어져도 줄바꿈하지 않고 한 줄로 유지 + 말줄임표(가운데)로
        # 줄인다 — 경로는 앞(드라이브)과 뒤(실제 폴더명) 둘 다 알아야 뜻이
        # 통하는 텍스트라 파일명 진행률 표시(gui/common_dialogs.py::
        # ProgressDialog.update_progress)와 같은 방식을 쓴다. 전체 경로는
        # 툴팁으로 항상 확인 가능(기본 정책, 2026-09-18).
        self.output_path_label = QLabel()
        self.output_path_label.setWordWrap(False)
        self.output_path_label.setStyleSheet("font-size: 12px;")
        output_row.addWidget(self.output_path_label, stretch=1)
        layout.addLayout(output_row)
        self.set_output_root(output_root)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton("정리 실행")
        self.confirm_btn.setObjectName("Primary")
        self.confirm_btn.setDefault(True)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        layout.addLayout(btn_row)

        self._update_confirm_enabled()

    def _on_change_output_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self._output_root or "")
        if chosen:
            self.set_output_root(chosen)

    def set_output_root(self, path: str) -> None:
        self._output_root = path
        self._refresh_output_label()

    def output_root(self) -> str:
        return self._output_root

    def _refresh_output_label(self) -> None:
        # 다이얼로그가 아직 화면에 안 떠서 실제 폭을 모를 때(생성 직후
        # set_output_root 호출)는 최소폭(setMinimumWidth(420)) 기준으로
        # 대략 추정 — 실제로 뜨면 resizeEvent가 정확한 폭으로 다시 계산한다.
        width = self.output_path_label.width() or (self.minimumWidth() - 120)
        metrics = self.output_path_label.fontMetrics()
        elided = metrics.elidedText(self._output_root, Qt.ElideMiddle, max(width, 0))
        self.output_path_label.setText(elided)
        self.output_path_label.setToolTip(self._output_root)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_output_label()

    def mode(self) -> str:
        return "move" if self.move_radio.isChecked() else "copy"

    def rename_settings(self):
        return self.rename_widget.settings()

    def _update_confirm_enabled(self) -> None:
        self.confirm_btn.setEnabled(self.rename_widget.is_valid())
