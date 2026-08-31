"""
gui/home_screen.py

PRD 16장 "Screen 01 — Home" 구현.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings, QStandardPaths, QPointF, QRectF, QUrl
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
    QDialog,
)

from core.converter import RecoveryMode
from core.scanner import SCANNABLE_EXTENSIONS
from gui.result_screen import SummaryChip
from gui.theme import COLORS, STATUS_COLORS
from utils.assets import asset_path

MAX_RECENT = 5
RECENT_SCANS_KEY = "recent_scans_v2"  # 이전 버전(단순 경로 문자열 목록)과 형식이 달라 키를 분리함
CONTENT_WIDTH = 520

_IMAGE_FILTER_PATTERN = " ".join(f"*{ext}" for ext in sorted(SCANNABLE_EXTENSIONS))
IMAGE_FILE_FILTER = f"이미지 파일 ({_IMAGE_FILTER_PATTERN});;모든 파일 (*)"


def _image_icon_pixmap(color: str, size: int = 28) -> QPixmap:
    """선택 카드 아이콘: 목업과 동일한 '사진' 아웃라인(폴더 이모지 대신 벡터로 그림)."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.7 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    frame = QRectF(3 * scale, 4 * scale, 18 * scale, 16 * scale)
    painter.drawRoundedRect(frame, 2.5 * scale, 2.5 * scale)
    painter.drawEllipse(QPointF(8.5 * scale, 9.5 * scale), 1.5 * scale, 1.5 * scale)

    mountains = QPainterPath()
    mountains.moveTo(4 * scale, 16.5 * scale)
    mountains.lineTo(9 * scale, 11.5 * scale)
    mountains.lineTo(12.5 * scale, 15 * scale)
    mountains.lineTo(17 * scale, 10 * scale)
    mountains.lineTo(20 * scale, 13.5 * scale)
    painter.drawPath(mountains)

    painter.end()
    return pixmap


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

        icon = QLabel()
        icon.setFixedSize(64, 64)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"background-color: {COLORS['selection']}; border-radius: 32px;"
        )
        icon.setPixmap(_image_icon_pixmap(COLORS["primary"], size=28))
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


def _status_icon_pixmap(ok: bool, accent: str, size: int = 24) -> QPixmap:
    """완료(✓)/중단(⚠) 상태를 원 안에 벡터로 그린 아이콘. 이모지 폰트를 쓰지 않아
    OS(윈도우 컬러 이모지 vs macOS)에 따라 색이 달라지는 문제를 피한다.

    목업은 24px 원 안에 13px짜리 아이콘을 중앙 배치한다(아이콘이 원을 거의
    다 채우지 않고 여백이 있음) — 그 비율(13/24)과 중앙 정렬 오프셋을 그대로 따른다.
    """
    icon_box = size * (13 / 24)
    inner_scale = icon_box / 24.0
    offset = (size - icon_box) / 2

    def pt(x: float, y: float) -> QPointF:
        return QPointF(offset + x * inner_scale, offset + y * inner_scale)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawEllipse(0, 0, size, size)

    if ok:
        pen = QPen(QColor("white"))
        pen.setWidthF(3 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        check = QPainterPath()
        check.moveTo(pt(5, 12.5))
        check.lineTo(pt(9.5, 17))
        check.lineTo(pt(19, 7))
        painter.drawPath(check)
    else:
        clip = QPainterPath()
        clip.addEllipse(0, 0, size, size)
        painter.setClipPath(clip)

        painter.setBrush(QColor("white"))
        triangle = QPainterPath()
        triangle.moveTo(pt(12, 4.5))
        triangle.lineTo(pt(21.5, 20.5))
        triangle.lineTo(pt(2.5, 20.5))
        triangle.closeSubpath()
        painter.drawPath(triangle)

        pen = QPen(QColor(accent))
        pen.setWidthF(2 * inner_scale)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(pt(12, 10.3), pt(12, 14.8))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawEllipse(pt(12, 17.5), 0.9 * inner_scale, 0.9 * inner_scale)

    painter.end()
    return pixmap


class _RecentRow(QFrame):
    """최근 검사 카드 안의 클릭 가능한 한 행."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RecentRow")
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
            row = self._build_row(
                entry, is_first=(idx == 0), is_last=(idx == len(entries) - 1)
            )
            self._layout.addWidget(row)

    def _build_row(self, entry: dict, is_first: bool, is_last: bool) -> QFrame:
        ok = entry.get("status") == "completed"
        accent = COLORS["success"] if ok else COLORS["warning"]

        row = _RecentRow()
        border = "none" if is_last else f"1px solid {COLORS['border']}"
        # 카드(RecentCard)의 border-radius:12px와 맞춰서, 첫/마지막 행의 바깥쪽 모서리만
        # 둥글게 해준다 — 안 그러면 행의 사각 배경이 카드의 둥근 모서리 밖으로 삐져나와 덮어버림.
        radius_css = "border-radius: 0;"
        if is_first and is_last:
            radius_css = "border-radius: 12px;"
        elif is_first:
            radius_css = "border-top-left-radius: 12px; border-top-right-radius: 12px;"
        elif is_last:
            radius_css = "border-bottom-left-radius: 12px; border-bottom-right-radius: 12px;"
        row.setStyleSheet(
            f"QFrame#RecentRow {{ background-color: {COLORS['surface']}; border: none; "
            f"border-bottom: {border}; {radius_css} }}"
            f"QFrame#RecentRow:hover {{ background-color: {COLORS['bg']}; }}"
        )
        row.clicked.connect(lambda entry=entry: self.entry_activated.emit(entry))

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(18, 13, 18, 13)
        row_layout.setSpacing(12)

        dot = QLabel()
        dot.setFixedSize(24, 24)
        dot.setPixmap(_status_icon_pixmap(ok, accent))
        row_layout.addWidget(dot)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        name = QLabel(entry.get("label", ""))
        name.setStyleSheet("font-weight: 500; font-size: 13.5px; background: transparent;")
        status_label = QLabel(_status_line(entry))
        status_label.setStyleSheet(f"color: {accent}; font-size: 12px; background: transparent;")
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
        header_row.setSpacing(6)

        brand_icon = QLabel()
        brand_icon.setFixedSize(44, 44)
        brand_icon.setPixmap(
            QPixmap(asset_path("icon.png")).scaled(
                44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        header_row.addWidget(brand_icon, alignment=Qt.AlignVCenter)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        title = QLabel("PicMedic")
        title.setStyleSheet("font-size: 20px; font-weight: 700; margin: 0; padding: 0;")
        subtitle = QLabel("사진을 치료해줄게요")
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12.5px; margin: 0; padding: 0;")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        header_row.addLayout(brand_text)
        header_row.setAlignment(brand_text, Qt.AlignVCenter)
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
        ok = entry.get("status") == "completed"
        accent = COLORS["success"] if ok else COLORS["warning"]

        dialog = QDialog(self)
        dialog.setWindowTitle("최근 검사 결과")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # 최근 검사 목록 행과 같은 완료(✓)/중단(⚠) 아이콘을 크게 재사용해서
        # 한눈에 결과 성격을 알 수 있게 한다 (DESIGN.md 아이콘 시스템 참고).
        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        icon_label = QLabel()
        icon_label.setPixmap(_status_icon_pixmap(ok, accent, size=40))
        header_row.addWidget(icon_label, alignment=Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(entry.get("label", ""))
        title_label.setWordWrap(True)
        title_label.setFixedWidth(240)
        title_label.setStyleSheet("font-weight: 700; font-size: 15px;")
        text_col.addWidget(title_label)

        status_label = QLabel(_status_line(entry))
        status_label.setStyleSheet(f"color: {accent}; font-weight: 600; font-size: 12.5px;")
        text_col.addWidget(status_label)

        meta_label = QLabel(f"검사 시각: {entry.get('timestamp', '-')}")
        meta_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px;")
        text_col.addWidget(meta_label)

        header_row.addLayout(text_col, 1)
        layout.addLayout(header_row)

        # 상태별 개수 — 검사 결과 화면과 같은 SummaryChip 카드(DESIGN.md "상태 요약
        # 카드"). 칸이 최대 6개까지 나올 수 있어 한 줄이 아니라 3열 그리드로 접는다.
        chip_defs = (
            ("normal", "정상", STATUS_COLORS["정상"]),
            ("mismatch", "형식 불일치", STATUS_COLORS["형식_불일치"]),
            ("partial_corruption", "부분 손상", STATUS_COLORS["부분_손상"]),
            ("corrupted", "손상", STATUS_COLORS["손상"]),
            ("unsupported", "지원 안 함", COLORS["muted"]),
            ("not_an_image", "이미지 아님", COLORS["muted"]),
        )
        present = [(label, color, entry.get(key, 0)) for key, label, color in chip_defs if entry.get(key, 0)]
        if present:
            grid = QGridLayout()
            grid.setSpacing(8)
            for idx, (label, color, value) in enumerate(present):
                chip = SummaryChip(label, color)
                chip.set_value(value)
                grid.addWidget(chip, idx // 3, idx % 3)
            layout.addLayout(grid)

        # 이 스캔을 기준으로 복구/변환까지 했었다면(main_window.py::_on_recovery_finished가
        # record_recovery_outcome으로 기록) 결과와 저장 폴더 바로가기를 보여준다. 복구 이후
        # 사용자가 폴더/파일을 옮기거나 지웠을 수 있으니, "복구했다는 기록"은 그대로 두되
        # 폴더가 실제로 있는지는 열기를 누르는 시점에 확인한다.
        recovery_dir = entry.get("recovery_output_dir")
        if recovery_dir:
            layout.addSpacing(2)
            recovery_row = QHBoxLayout()
            recovery_row.setSpacing(8)
            recovery_icon = QLabel()
            recovery_icon.setPixmap(_status_icon_pixmap(True, COLORS["success"], size=18))
            recovery_row.addWidget(recovery_icon)
            recovery_kind = "변환 완료" if entry.get("recovery_mode") == RecoveryMode.CONVERT.value else "복구 완료"
            recovery_label = QLabel(f"{recovery_kind} · {entry.get('recovery_count', 0)}개")
            recovery_label.setStyleSheet(f"color: {COLORS['success']}; font-weight: 600; font-size: 12.5px;")
            recovery_row.addWidget(recovery_label)
            recovery_row.addStretch(1)
            open_folder_btn = QPushButton("폴더 열기")
            recovery_row.addWidget(open_folder_btn)
            layout.addLayout(recovery_row)

            folder_missing_label = QLabel("폴더를 찾을 수 없습니다 — 이동되었거나 삭제된 것 같아요.")
            folder_missing_label.setWordWrap(True)
            folder_missing_label.setStyleSheet(f"color: {COLORS['danger']}; font-size: 11.5px;")
            folder_missing_label.hide()
            layout.addWidget(folder_missing_label)

            def open_recovery_folder():
                if Path(recovery_dir).exists():
                    QDesktopServices.openUrl(QUrl.fromLocalFile(recovery_dir))
                else:
                    folder_missing_label.show()

            open_folder_btn.clicked.connect(open_recovery_folder)

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

    def record_recovery_outcome(self, paths: list[str], outcomes: list, output_dir: str) -> None:
        """복구/변환이 끝나면(main_window.py::_on_recovery_finished) 같은 원본 경로(paths)로
        기록된 '최근 검사' 항목에 결과 폴더를 남겨서, 최근 검사 팝업에서 바로 열 수 있게 한다.
        같은 스캔을 여러 번 복구했으면 가장 최근 것만 남는다(이력 전체를 쌓지 않음)."""
        recovered_count = sum(1 for o in outcomes if o.success)
        if not paths or not recovered_count:
            return

        entries = self._load_recent_entries()
        for entry in entries:
            if entry.get("paths") == paths:
                entry["recovery_output_dir"] = output_dir
                entry["recovery_count"] = recovered_count
                # 배치 하나는 항상 모드 하나(gui/recovery_screen.py::_start_recovery가
                # RESTORE_EXTENSION/CONVERT 중 하나로만 recover_batch를 호출)라
                # 첫 outcome의 mode만 봐도 된다 — "복구 완료"/"변환 완료" 문구를 결정.
                entry["recovery_mode"] = outcomes[0].mode.value
                self._save_recent_entries(entries)
                self._refresh_recent_list()
                return

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
