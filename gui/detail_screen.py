"""
gui/detail_screen.py

PRD 19장 "Screen 04 — File Detail" 구현.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGridLayout,
)

from core.converter import RecoveryMode
from gui.image_viewer import ImageViewer
from gui.quality_diagnosis_dialog import run_quality_diagnosis
from gui.theme import COLORS, STATUS_COLORS
from models.file_info import FileInfo, FileStatus
from utils.file_utils import format_file_size

PREVIEW_SIZE = 320


class DetailScreen(QWidget):
    back_requested = Signal()
    recover_requested = Signal(list, object)  # [FileInfo], RecoveryMode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_info: FileInfo | None = None
        # 중복/유사 사진 화면에서 "미리보기"로 열렸을 때는 편집 액션(복구/
        # 변환/화질 개선)을 감춘다 — set_review_only() 참고.
        self._review_only = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(16)

        back_btn = QPushButton("\u2190 목록으로")
        back_btn.clicked.connect(self.back_requested.emit)
        outer.addWidget(back_btn, alignment=Qt.AlignLeft)

        content_col = QVBoxLayout()
        content_col.setSpacing(24)

        # --- 위: 미리보기 ---
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setAlignment(Qt.AlignCenter)
        self.preview_viewer = ImageViewer(placeholder_text="미리보기를 생성할 수 없습니다.")
        self.preview_viewer.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE + 28)
        preview_layout.addWidget(self.preview_viewer)
        content_col.addWidget(preview_card, alignment=Qt.AlignHCenter)

        # --- 아래: 정보 + 액션 ---
        info_card = QFrame()
        info_card.setObjectName("Card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(24, 24, 24, 24)
        info_layout.setSpacing(12)

        self.filename_label = QLabel()
        self.filename_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        info_layout.addWidget(self.filename_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.grid = grid
        self._grid_row = 0
        info_layout.addLayout(grid)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        info_layout.addWidget(self.warning_label)

        self.recovery_note_label = QLabel()
        self.recovery_note_label.setWordWrap(True)
        info_layout.addWidget(self.recovery_note_label)

        info_layout.addStretch(1)

        btn_row = QHBoxLayout()
        self.diagnose_btn = QPushButton("사진 진단")
        self.diagnose_btn.setToolTip(
            "블러/노이즈/얼굴 흐림 등을 실제로 분석해서\n"
            "어떤 복원 기능이 맞는지 추천합니다."
        )
        self.diagnose_btn.clicked.connect(self._on_diagnose_clicked)
        btn_row.addWidget(self.diagnose_btn)
        self.restore_btn = QPushButton("실제 형식으로 복구")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        self.convert_btn = QPushButton("확장자 변환")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.clicked.connect(self._on_convert_clicked)
        btn_row.addWidget(self.restore_btn)
        btn_row.addWidget(self.convert_btn)
        info_layout.addLayout(btn_row)

        content_col.addWidget(info_card)
        outer.addLayout(content_col, stretch=1)

    # --- 외부에서 호출 --------------------------------------------------

    def set_review_only(self, review_only: bool) -> None:
        """중복/유사 사진 화면에서 사진을 클릭해 "이게 정말 맞나" 확인만 하러
        들어왔을 때 True로 준다 — gui/date_group_detail_screen.py와 같은
        원칙: 정리 대상을 확인하는 화면에 복구/변환/화질 개선 같은 편집
        액션이 같이 있으면 오히려 헷갈린다(실사용 피드백). set_file() 호출
        전후 아무 때나 불러도 되고, 다음 set_file()부터 반영된다."""
        self._review_only = review_only

    def set_file(self, info: FileInfo):
        self.current_info = info
        self.filename_label.setText(info.filename)

        self._clear_grid()
        self._add_row("파일 확장자", info.extension or "-")
        self._add_row("실제 형식", info.detected_format or "알 수 없음")
        self._add_row("파일 크기", format_file_size(info.file_size))
        if info.width and info.height:
            self._add_row("해상도", f"{info.width} × {info.height}")
        else:
            self._add_row("해상도", "-")
        status_color = STATUS_COLORS.get(info.status.value, COLORS["text"])
        self._add_row("상태", info.status.value.replace("_", " "), color=status_color)

        if info.is_mismatched:
            self.warning_label.setText("\u26a0 파일 확장자와 실제 이미지 형식이 일치하지 않습니다.")
            self.warning_label.show()
        elif info.status == FileStatus.CORRUPTED:
            self.warning_label.setText("\u26a0 이미지를 정상적으로 읽을 수 없습니다. 복구가 어려울 수 있습니다.")
            self.warning_label.show()
        elif info.status == FileStatus.PARTIAL_CORRUPTION:
            self.warning_label.setText("\u26a0 파일 일부가 손상되었습니다. 일부만 복구될 수 있습니다.")
            self.warning_label.show()
        else:
            self.warning_label.hide()

        recoverable = info.status in (FileStatus.MISMATCH, FileStatus.PARTIAL_CORRUPTION)
        # "복구"는 문제가 있는 파일에만 의미가 있으므로 그런 파일에서만 보여준다.
        # (review_only면 어떤 상태든 액션 자체를 감춘다 — set_review_only() 참고.)
        # "사진 진단"은 is_available() 게이팅 없음 — Pillow 부분은 항상 되고,
        # 얼굴 탐지 부분만 facexlib 자산 여부에 따라 결과에서 조용히 생략된다
        # (core/quality_diagnosis.py::detect_faces).
        self.diagnose_btn.setVisible(not self._review_only)
        self.diagnose_btn.setEnabled(info.readable)
        self.restore_btn.setVisible(recoverable and not self._review_only)
        self.restore_btn.setEnabled(recoverable and bool(info.detected_format))
        # "변환"은 복구와 무관하게, 디코딩만 된다면(readable) 정상 파일도 다른 형식으로
        # 바꿀 수 있어야 한다 (예: 정상 PNG를 웹 업로드용 WEBP로).
        self.convert_btn.setVisible(not self._review_only)
        self.convert_btn.setEnabled(info.readable)
        if self._review_only:
            self.recovery_note_label.setText("")
        elif recoverable:
            self.recovery_note_label.setText(
                "높은 확률로 복구할 수 있습니다."
                if info.status == FileStatus.MISMATCH
                else "일부 데이터가 손상되어 결과가 완전하지 않을 수 있습니다."
            )
        elif info.status == FileStatus.NORMAL:
            self.recovery_note_label.setText("다른 파일 형식으로 변환할 수 있습니다.")
        else:
            self.recovery_note_label.setText("")

        self.restore_btn.setText(
            f"{info.detected_format or '원본'} 형식으로 복구" if info.detected_format else "확장자 복구"
        )

        self._load_preview(info)

    # --- 내부 로직 -----------------------------------------------------

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._grid_row = 0

    def _add_row(self, label: str, value: str, color: str | None = None):
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        value_widget = QLabel(value)
        if color:
            value_widget.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.grid.addWidget(label_widget, self._grid_row, 0)
        self.grid.addWidget(value_widget, self._grid_row, 1)
        self._grid_row += 1

    def _load_preview(self, info: FileInfo):
        self.preview_viewer.set_image_path(info.path)

    def _on_restore_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.RESTORE_EXTENSION)

    def _on_convert_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.CONVERT)

    def _on_diagnose_clicked(self):
        info = self.current_info
        if not info:
            return
        run_quality_diagnosis(self, info.path, info.width, info.height)
