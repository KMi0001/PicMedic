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
from core import quality_enhancer
from gui.quality_enhance_dialog import run_quality_enhancement
from gui.theme import COLORS, STATUS_COLORS
from models.file_info import FileInfo, FileStatus
from utils.file_utils import format_file_size

PREVIEW_SIZE = 320
# 화질 개선 대상으로 안내할 기준 — 이보다 크면 이미 충분히 고화질이라 굳이
# 4배로 더 키울 필요가 적고, 시간만 오래 걸린다(실측: core/quality_enhancer.py
# 참고, 처리 시간이 출력 픽셀 수에 비례해서 고화질 사진일수록 더 오래 걸림).
LOW_RES_HINT_THRESHOLD = 1_000_000  # 총 픽셀 수 100만(예: 1000x1000) 미만


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

        self.enhance_hint_label = QLabel()
        self.enhance_hint_label.setWordWrap(True)
        self.enhance_hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        info_layout.addWidget(self.enhance_hint_label)

        info_layout.addStretch(1)

        btn_row = QHBoxLayout()
        self.restore_btn = QPushButton("실제 형식으로 복구")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        self.convert_btn = QPushButton("확장자 변환")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.clicked.connect(self._on_convert_clicked)
        self.enhance_btn = QPushButton("화질 개선")
        self.enhance_btn.setToolTip(
            "사진을 더 선명하게 확대합니다. 사라진 디테일이 되살아나는 것은 아니고,\n"
            "단순 확대보다 덜 뭉개지게 키워주는 기능입니다."
        )
        self.enhance_btn.clicked.connect(self._on_enhance_clicked)
        btn_row.addWidget(self.restore_btn)
        btn_row.addWidget(self.convert_btn)
        btn_row.addWidget(self.enhance_btn)
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

        # 화질 개선은 이 기기에 실행 파일이 준비돼 있고(is_available), 디코딩이
        # 되는 파일에만 의미가 있다 — 폴더 일괄이 아니라 사진 한 장 단위로만
        # 제공한다(core/quality_enhancer.py 참고, 처리 시간이 커서 일괄 처리엔 부적합).
        enhance_ready = quality_enhancer.is_available() and info.readable
        self.enhance_btn.setVisible(quality_enhancer.is_available())
        self.enhance_btn.setEnabled(enhance_ready)
        if enhance_ready and info.width and info.height and info.width * info.height < LOW_RES_HINT_THRESHOLD:
            self.enhance_hint_label.setText(
                "저해상도 사진이에요 — \"화질 개선\"으로 더 선명하게 확대해볼 수 있어요."
            )
        else:
            self.enhance_hint_label.setText("")

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

    def _on_enhance_clicked(self):
        info = self.current_info
        if not info:
            return
        run_quality_enhancement(self, info.path, info.width, info.height)
