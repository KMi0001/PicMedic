"""
gui/trash_screen.py

Phase 2 "사진 정리" — utils/trash.py::TRASH_DIR(임시 휴지통)에 옮겨진 파일 목록을
보여주는 화면. 선택한 파일을 원래 있던 폴더로 복원하거나(영구 삭제는 아직 없음 —
필요하면 탐색기/Finder에서 직접 처리), 폴더를 직접 열어 볼 수 있다.
gui/duplicate_screen.py에서 파일을 휴지통으로 옮긴 직후 이 화면으로 넘어온다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)

from gui.common_dialogs import info_dialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS
from utils import trash
from utils.file_utils import format_file_size


def _trash_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 휴지통 모양 아웃라인. 다른 페이지 제목 아이콘과 같은
    스트로크 스타일(검사 결과의 돋보기, 복구의 화살표 등)."""
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
    painter.setBrush(Qt.NoBrush)

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    def p(x, y):
        from PySide6.QtCore import QPointF

        return QPointF(x * scale, y * scale)

    painter.drawLine(p(4, 7), p(20, 7))
    painter.drawLine(p(9, 4), p(15, 4))
    painter.drawRoundedRect(r(6, 7, 12, 14), 1.5 * scale, 1.5 * scale)
    painter.drawLine(p(10, 11), p(10, 17))
    painter.drawLine(p(14, 11), p(14, 17))

    painter.end()
    return pixmap


class TrashScreen(QWidget):
    """utils/trash.py의 임시 휴지통 내용을 보여주는 화면. 같은 스캔 세션 안에서만
    쓰인다(gui/scan_session_window.py)."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_trash_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("임시 휴지통")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        self.count_chip = SummaryChip("보관된 파일", COLORS["muted"])
        chips_row = QHBoxLayout()
        chips_row.addWidget(self.count_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "완전히 삭제된 게 아니라 이 폴더로 옮겨진 것뿐이에요. "
            "다시 필요하면 목록에서 선택 후 \"선택 항목 복원\"으로 원래 위치에 되돌릴 수 있고, "
            "필요 없으면 폴더를 열어서 직접 정리해주세요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        outer.addWidget(self.list_widget, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        restore_btn = QPushButton("선택 항목 복원")
        restore_btn.clicked.connect(self._on_restore_clicked)
        btn_row.addWidget(restore_btn)
        open_folder_btn = QPushButton("임시 휴지통 폴더 열기")
        open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_folder_btn)
        outer.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        """utils/trash.py의 실제 폴더 내용을 다시 읽어와 목록을 갱신한다."""
        files = trash.list_trash()
        self.count_chip.set_value(len(files))

        self.list_widget.clear()
        if files:
            for path in files:
                size = format_file_size(path.stat().st_size) if path.exists() else "-"
                item = QListWidgetItem(f"{path.name} · {size}")
                item.setData(Qt.UserRole, str(path))
                self.list_widget.addItem(item)
        else:
            placeholder = QListWidgetItem("임시 휴지통이 비어 있습니다.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)

    def _on_restore_clicked(self):
        items = self.list_widget.selectedItems()
        paths = [item.data(Qt.UserRole) for item in items if item.data(Qt.UserRole)]
        if not paths:
            info_dialog(self, "복원할 파일을 먼저 목록에서 선택해주세요.")
            return

        restored = 0
        failed: list[str] = []
        for path in paths:
            try:
                trash.restore_from_trash(path)
                restored += 1
            except (ValueError, OSError) as exc:
                failed.append(f"{Path(path).name} ({exc})")

        self.refresh()

        if failed:
            info_dialog(
                self,
                f"{restored}개 복원했습니다.\n"
                f"{len(failed)}개는 복원하지 못했습니다:\n" + "\n".join(failed),
            )
        else:
            info_dialog(self, f"{restored}개 파일을 원래 위치로 복원했습니다.")

    def _open_folder(self):
        trash.trash_dir().mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(trash.trash_dir())))
