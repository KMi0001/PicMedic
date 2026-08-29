"""
gui/scanning_screen.py

PRD 17장 "Screen 02 — Scanning" 구현.
검사는 별도 QThread에서 실행하여 UI가 멈추지 않도록 한다 (NFR '성능').
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QFrame,
)

from core.scanner import scan_paths
from gui.theme import COLORS


class ScanWorker(QThread):
    progress = Signal(int, int, str)           # current, total, filename
    finished_scan = Signal(object, bool, list)  # ScanResult, cancelled, remaining_paths

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self.paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        result, remaining_paths = scan_paths(
            self.paths,
            recursive=True,
            progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
            should_cancel=lambda: self._cancel_requested,
        )
        self.finished_scan.emit(result, self._cancel_requested, remaining_paths)


class ScanningScreen(QWidget):
    scan_finished = Signal(object, bool, int, list)  # ScanResult, cancelled, planned_total, remaining_paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: ScanWorker | None = None
        self._start_time = 0.0
        self._planned_total = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 48)
        outer.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(480)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(14)

        self.title_label = QLabel("사진 검사 중...")
        self.title_label.setObjectName("Title")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        card_layout.addWidget(self.title_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        self.count_label = QLabel("0 / 0")
        self.count_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        card_layout.addWidget(self.count_label)

        self.current_file_label = QLabel("현재 검사: -")
        self.current_file_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        card_layout.addWidget(self.current_file_label)

        time_row = QVBoxLayout()
        self.elapsed_label = QLabel("경과 시간: 0초")
        self.eta_label = QLabel("예상 남은 시간: 계산 중...")
        for lbl in (self.elapsed_label, self.eta_label):
            lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            time_row.addWidget(lbl)
        card_layout.addLayout(time_row)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.clicked.connect(self._on_cancel)
        card_layout.addWidget(self.cancel_btn, alignment=Qt.AlignCenter)

        outer.addWidget(card)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_elapsed)

    def start_scan(self, paths: list[str]):
        self.title_label.setText("사진 검사 중...")
        self.progress_bar.setValue(0)
        self.count_label.setText("0 / 0")
        self.current_file_label.setText("현재 검사: -")
        self.eta_label.setText("예상 남은 시간: 계산 중...")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("취소")
        self._planned_total = 0

        self._start_time = time.time()
        self._timer.start()

        self.worker = ScanWorker(paths)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_scan.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, current: int, total: int, filename: str):
        self._planned_total = total
        pct = int((current / total) * 100) if total else 0
        self.progress_bar.setValue(pct)
        self.count_label.setText(f"{current:,} / {total:,}")
        self.current_file_label.setText(f"현재 검사: {filename}")

        elapsed = time.time() - self._start_time
        if current > 0 and total:
            rate = elapsed / current
            remaining = max(0, (total - current) * rate)
            self.eta_label.setText(f"예상 남은 시간: 약 {int(remaining)}초")

    def _update_elapsed(self):
        elapsed = int(time.time() - self._start_time)
        self.elapsed_label.setText(f"경과 시간: {elapsed}초")

    def _on_finished(self, result, cancelled: bool, remaining_paths: list):
        self._timer.stop()
        if not cancelled:
            self.progress_bar.setValue(100)
        self.scan_finished.emit(result, cancelled, self._planned_total, remaining_paths)

    def _on_cancel(self):
        if self.worker:
            self.worker.cancel()
        # 화면 전환은 워커가 실제로 멈추고 finished_scan을 보내온 뒤에만 한다
        # (즉시 전환하면 뒤늦게 도착하는 finished_scan이 화면을 다시 덮어써버리는 문제가 있었음)
        self.title_label.setText("취소하는 중...")
        self.current_file_label.setText("현재까지 검사한 내용을 정리하고 있습니다...")
        self.cancel_btn.setEnabled(False)
