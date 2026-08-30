"""
gui/detail_screen.py

PRD 19장 "Screen 04 — File Detail" 구현.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage
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
        self.preview_label = QLabel("미리보기를 생성할 수 없습니다.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        preview_layout.addWidget(self.preview_label)
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
        self.restore_btn = QPushButton("실제 형식으로 복구")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        self.convert_btn = QPushButton("JPEG로 변환")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.clicked.connect(self._on_convert_clicked)
        btn_row.addWidget(self.restore_btn)
        btn_row.addWidget(self.convert_btn)
        info_layout.addLayout(btn_row)

        content_col.addWidget(info_card)
        outer.addLayout(content_col, stretch=1)

    # --- 외부에서 호출 --------------------------------------------------

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
        self.restore_btn.setVisible(recoverable)
        self.restore_btn.setEnabled(recoverable and bool(info.detected_format))
        # "변환"은 복구와 무관하게, 디코딩만 된다면(readable) 정상 파일도 다른 형식으로
        # 바꿀 수 있어야 한다 (예: 정상 PNG를 웹 업로드용 WEBP로).
        self.convert_btn.setEnabled(info.readable)
        if recoverable:
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
        pixmap = None
        try:
            if info.detected_format in ("HEIC", "HEIF"):
                from PIL import Image
                from PIL.ImageQt import ImageQt

                with Image.open(info.path) as img:
                    img.load()
                    img.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
                    qimage = ImageQt(img.convert("RGBA"))
                    pixmap = QPixmap.fromImage(QImage(qimage))
            else:
                candidate = QPixmap(info.path)
                if not candidate.isNull():
                    pixmap = candidate.scaled(
                        PREVIEW_SIZE, PREVIEW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
        except Exception:
            pixmap = None

        if pixmap and not pixmap.isNull():
            self.preview_label.setPixmap(pixmap)
            self.preview_label.setText("")
        else:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("미리보기를 생성할 수 없습니다.")

    def _on_restore_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.RESTORE_EXTENSION)

    def _on_convert_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.CONVERT)
