"""
gui/home_screen.py

PRD 16장 "Screen 01 — Home" 구현.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings, QStandardPaths
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QDialog,
)

from core.scanner import SCANNABLE_EXTENSIONS
from gui.theme import COLORS

MAX_RECENT = 5
RECENT_SCANS_KEY = "recent_scans_v2"  # 이전 버전(단순 경로 문자열 목록)과 형식이 달라 키를 분리함

_IMAGE_FILTER_PATTERN = " ".join(f"*{ext}" for ext in sorted(SCANNABLE_EXTENSIONS))
IMAGE_FILE_FILTER = f"이미지 파일 ({_IMAGE_FILTER_PATTERN});;모든 파일 (*)"


class DropArea(QFrame):
    """파일/폴더를 끌어놓을 수 있는 영역 (PRD '파일을 여기에 끌어놓으세요')"""

    paths_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("\U0001F4C1")  # 📁
        icon.setStyleSheet("font-size: 32px;")
        icon.setAlignment(Qt.AlignCenter)

        self.label = QLabel("파일을 여기에 끌어놓으세요")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(f"color: {COLORS['text_secondary']};")

        layout.addWidget(icon)
        layout.addWidget(self.label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"border: 2px dashed {COLORS['primary']}; border-radius: 12px;")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.toLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)


class HomeScreen(QWidget):
    """검사할 폴더/파일을 선택하는 첫 화면"""

    paths_chosen = Signal(list)  # list[str] — 파일 1개 이상 / 폴더 1개

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PicMedic", "PicMedic")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.setSpacing(20)
        outer.setAlignment(Qt.AlignTop)

        title = QLabel("PicMedic")
        title.setObjectName("Title")
        subtitle = QLabel("사진을 검사하고 복구하세요")
        subtitle.setObjectName("Subtitle")

        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(12)

        select_row = QHBoxLayout()
        select_row.setSpacing(10)

        file_btn = QPushButton("파일 선택")
        file_btn.setFixedWidth(140)
        file_btn.clicked.connect(self._choose_file)
        select_row.addWidget(file_btn)

        folder_btn = QPushButton("폴더 선택")
        folder_btn.setObjectName("Primary")
        folder_btn.setFixedWidth(140)
        folder_btn.clicked.connect(self._choose_folder)
        select_row.addWidget(folder_btn)

        select_row.addStretch(1)
        outer.addLayout(select_row)

        self.drop_area = DropArea()
        self.drop_area.paths_dropped.connect(self._on_paths_chosen)
        outer.addWidget(self.drop_area)

        recent_label = QLabel("최근 검사")
        recent_label.setStyleSheet("font-weight: 600; margin-top: 8px;")
        outer.addWidget(recent_label)

        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(140)
        self.recent_list.itemDoubleClicked.connect(self._on_recent_double_clicked)
        outer.addWidget(self.recent_list)

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

    def _on_recent_double_clicked(self, item: QListWidgetItem):
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        self._show_recent_summary(entry)

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
        self.recent_list.clear()
        entries = self._load_recent_entries()
        for entry in entries:
            item = QListWidgetItem(f"\u2022 {_format_recent_entry(entry)}")
            item.setData(Qt.UserRole, entry)
            self.recent_list.addItem(item)
        if not entries:
            placeholder = QListWidgetItem("최근 검사 기록이 없습니다.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(placeholder)


def _status_line(entry: dict) -> str:
    status = entry.get("status")
    scanned = entry.get("scanned", 0)
    planned = entry.get("planned", scanned)

    if status == "completed":
        return f"✓ 완료 ({scanned:,}장)"
    elif status == "cancelled":
        return f"⚠ 중단됨 ({scanned:,}/{planned:,})"
    return ""


def _format_recent_entry(entry: dict) -> str:
    label = entry.get("label", "")
    status_text = _status_line(entry)
    return f"{label}   —   {status_text}" if status_text else label
