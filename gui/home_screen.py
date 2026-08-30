"""
gui/home_screen.py

PRD 16장 "Screen 01 — Home" 구현.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings, QStandardPaths
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
    QDialog,
)

from core.scanner import SCANNABLE_EXTENSIONS
from gui.theme import COLORS
from utils.assets import asset_path

MAX_RECENT = 5
RECENT_SCANS_KEY = "recent_scans_v2"  # 이전 버전(단순 경로 문자열 목록)과 형식이 달라 키를 분리함
CONTENT_WIDTH = 520

_IMAGE_FILTER_PATTERN = " ".join(f"*{ext}" for ext in sorted(SCANNABLE_EXTENSIONS))
IMAGE_FILE_FILTER = f"이미지 파일 ({_IMAGE_FILTER_PATTERN});;모든 파일 (*)"


class SelectionCard(QFrame):
    """파일/폴더 선택 버튼과 드래그 앤 드롭 영역을 하나로 묶은 카드."""

    paths_dropped = Signal(list)
    file_requested = Signal()
    folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SelectionCard")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 32, 28, 32)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("\U0001F4C1")  # 📁
        icon.setFixedSize(64, 64)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"font-size: 26px; background-color: {COLORS['selection']}; border-radius: 32px;"
        )
        layout.addWidget(icon, alignment=Qt.AlignCenter)

        heading = QLabel("파일이나 폴더를 선택하세요")
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
        layout.addWidget(heading)

        hint = QLabel("이 영역에 끌어놓아도 됩니다")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(hint)

        layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        file_btn = QPushButton("파일 선택")
        file_btn.clicked.connect(self.file_requested.emit)
        btn_row.addWidget(file_btn)

        folder_btn = QPushButton("폴더 선택")
        folder_btn.setObjectName("Primary")
        folder_btn.clicked.connect(self.folder_requested.emit)
        btn_row.addWidget(folder_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"border: 2px dashed {COLORS['primary']}; border-radius: 16px;")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.toLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)


class _RecentRow(QFrame):
    """최근 검사 카드 안의 클릭 가능한 한 행."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class RecentCard(QFrame):
    """최근 검사 목록을 상태 아이콘 + 화살표가 있는 카드형 행으로 보여준다."""

    entry_activated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def set_entries(self, entries: list[dict]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not entries:
            placeholder = QLabel("최근 검사 기록이 없습니다.")
            placeholder.setStyleSheet(f"color: {COLORS['muted']}; padding: 16px;")
            self._layout.addWidget(placeholder)
            return

        for idx, entry in enumerate(entries):
            row = self._build_row(entry, is_last=(idx == len(entries) - 1))
            self._layout.addWidget(row)

    def _build_row(self, entry: dict, is_last: bool) -> QFrame:
        ok = entry.get("status") == "completed"
        accent = COLORS["success"] if ok else COLORS["warning"]

        row = _RecentRow()
        border = "none" if is_last else f"1px solid {COLORS['border']}"
        row.setStyleSheet(
            f"QFrame {{ border: none; border-bottom: {border}; }}"
            f"QFrame:hover {{ background-color: {COLORS['bg']}; }}"
        )
        row.clicked.connect(lambda entry=entry: self.entry_activated.emit(entry))

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(12)

        dot = QLabel("✓" if ok else "⚠")  # ✓ / ⚠
        dot.setFixedSize(24, 24)
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(
            f"background-color: {accent}; color: white; border-radius: 12px; "
            f"font-weight: 700; font-size: 11px;"
        )
        row_layout.addWidget(dot)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        name = QLabel(entry.get("label", ""))
        name.setStyleSheet("font-weight: 500; background: transparent;")
        status_label = QLabel(_status_line(entry))
        status_label.setStyleSheet(f"color: {accent}; font-size: 11px; background: transparent;")
        text_col.addWidget(name)
        text_col.addWidget(status_label)
        row_layout.addLayout(text_col, 1)

        chevron = QLabel("›")  # ›
        chevron.setStyleSheet(
            f"color: {COLORS['muted']}; font-size: 16px; font-weight: 700; background: transparent;"
        )
        row_layout.addWidget(chevron)

        return row


class HomeScreen(QWidget):
    """검사할 폴더/파일을 선택하는 첫 화면"""

    paths_chosen = Signal(list)  # list[str] — 파일 1개 이상 / 폴더 1개

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PicMedic", "PicMedic")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.setAlignment(Qt.AlignTop)

        content = QWidget()
        content.setFixedWidth(CONTENT_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        brand_icon = QLabel()
        brand_icon.setFixedSize(44, 44)
        brand_icon.setPixmap(
            QPixmap(asset_path("icon.png")).scaled(
                44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        header_row.addWidget(brand_icon)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        title = QLabel("PicMedic")
        title.setStyleSheet("font-size: 20px; font-weight: 700; margin-top: 8px;")
        subtitle = QLabel("사진을 치료해줄게요")
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12.5px;")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        header_row.addLayout(brand_text)
        header_row.addStretch(1)

        content_layout.addLayout(header_row)

        self.selection_card = SelectionCard()
        self.selection_card.paths_dropped.connect(self._on_paths_chosen)
        self.selection_card.file_requested.connect(self._choose_file)
        self.selection_card.folder_requested.connect(self._choose_folder)
        content_layout.addWidget(self.selection_card)

        recent_label = QLabel("최근 검사")
        recent_label.setStyleSheet("font-weight: 600;")
        content_layout.addWidget(recent_label)

        self.recent_card = RecentCard()
        self.recent_card.entry_activated.connect(self._show_recent_summary)
        content_layout.addWidget(self.recent_card)

        outer.addWidget(content, alignment=Qt.AlignHCenter)
        outer.addStretch(1)

        self._refresh_recent_list()

    # --- 내부 로직 -----------------------------------------------------

    def _default_browse_dir(self) -> str:
        """이전에 썼던 폴더가 있으면 그곳을, 없으면 시스템 '사진' 폴더를 기본 위치로 삼는다."""
        last = self.settings.value("last_browse_dir", "")
        if last and Path(last).exists():
            return last
        pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        return pictures or ""

    def _remember_browse_dir(self, directory: str):
        if directory:
            self.settings.setValue("last_browse_dir", directory)

    def _choose_file(self):
        start_dir = self._default_browse_dir()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "검사할 사진 파일 선택 (여러 개 선택 가능)", start_dir, IMAGE_FILE_FILTER
        )
        if file_paths:
            self._remember_browse_dir(str(Path(file_paths[0]).parent))
            self._on_paths_chosen(file_paths)

    def _choose_folder(self):
        start_dir = self._default_browse_dir()
        folder = QFileDialog.getExistingDirectory(self, "검사할 폴더 선택", start_dir)
        if folder:
            self._remember_browse_dir(folder)
            self._on_paths_chosen([folder])

    def _on_paths_chosen(self, paths: list[str]):
        valid = [p for p in paths if Path(p).exists()]
        if valid:
            self.paths_chosen.emit(valid)

    def _show_recent_summary(self, entry: dict):
        """스캔을 다시 하지 않고, 그때 결과 요약을 팝업으로 보여준다."""
        paths = entry.get("paths", [])

        dialog = QDialog(self)
        dialog.setWindowTitle("최근 검사 결과")
        dialog.resize(360, 320)
        layout = QVBoxLayout(dialog)

        title_label = QLabel(entry.get("label", ""))
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title_label)

        meta_label = QLabel(f"검사 시각: {entry.get('timestamp', '-')}")
        meta_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(meta_label)

        status_label = QLabel(_status_line(entry))
        layout.addWidget(status_label)

        layout.addSpacing(6)

        for key, label_text in (
            ("normal", "정상"),
            ("mismatch", "형식 불일치"),
            ("partial_corruption", "부분 손상"),
            ("corrupted", "손상"),
            ("unsupported", "지원 안 함"),
            ("not_an_image", "이미지 아님"),
        ):
            value = entry.get(key, 0)
            if value:
                layout.addWidget(QLabel(f"{label_text}: {value:,}"))

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        rescan_btn = QPushButton("다시 검사")
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("Primary")
        btn_row.addWidget(rescan_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        def do_rescan():
            dialog.accept()
            valid = [p for p in paths if Path(p).exists()]
            if valid:
                self.paths_chosen.emit(valid)

        rescan_btn.clicked.connect(do_rescan)
        close_btn.clicked.connect(dialog.reject)
        dialog.exec()

    # --- 최근 검사 기록 (스캔이 끝난 뒤 main_window가 호출) -------------------

    def record_scan_outcome(self, paths: list[str], result, cancelled: bool, planned_total: int) -> None:
        """스캔 1회가 끝나면(완료든 취소든) 결과를 '최근 검사' 목록에 기록한다."""
        if not paths or result.total == 0:
            # 검증된 파일이 하나도 없는 스캔은 목록에 남길 의미가 없다
            return

        label = paths[0] if len(paths) == 1 else f"{len(paths)}개 파일 선택"
        entry = {
            "paths": paths,
            "label": label,
            "status": "cancelled" if cancelled else "completed",
            "scanned": result.total,
            "planned": planned_total or result.total,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "normal": result.normal,
            "mismatch": result.mismatch,
            "partial_corruption": result.partial_corruption,
            "corrupted": result.corrupted,
            "unsupported": result.unsupported,
            "not_an_image": result.not_an_image,
        }

        entries = self._load_recent_entries()
        entries = [e for e in entries if e.get("paths") != paths]
        entries.insert(0, entry)
        entries = entries[:MAX_RECENT]
        self._save_recent_entries(entries)
        self._refresh_recent_list()

    def _load_recent_entries(self) -> list[dict]:
        raw = self.settings.value(RECENT_SCANS_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save_recent_entries(self, entries: list[dict]) -> None:
        self.settings.setValue(RECENT_SCANS_KEY, json.dumps(entries, ensure_ascii=False))

    def _refresh_recent_list(self):
        self.recent_card.set_entries(self._load_recent_entries())


def _status_line(entry: dict) -> str:
    status = entry.get("status")
    scanned = entry.get("scanned", 0)
    planned = entry.get("planned", scanned)

    if status == "completed":
        return f"완료 · {scanned:,}장"
    elif status == "cancelled":
        return f"중단됨 · {scanned:,}/{planned:,}"
    return ""
