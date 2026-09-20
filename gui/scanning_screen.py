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

from core.scanner import scan_paths, scan_paths_incremental
from core.session_store import load_session
from gui.theme import COLORS


class ScanWorker(QThread):
    progress = Signal(int, int, str)           # current, total, filename
    finished_scan = Signal(object, bool, list)  # ScanResult, cancelled, remaining_paths
    heavy_format_detected = Signal()            # HEIC/HEIF 발견 시 1회만(core/scanner.py 참고)
    failed = Signal(str)                        # 예상 못한 예외 (아래 run() 참고)

    def __init__(self, paths: list[str], use_saved_session: bool = False, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.use_saved_session = use_saved_session
        # 저장된 작업을 불러와 검사했으면 run()이 채워 둔다 — 창(gui/scan_session_window.py)이
        # 끝난 뒤 읽어서 카테고리 분류 결과를 복원하고 변경 요약을 띄우는 데 쓴다.
        self.saved_session = None  # core.session_store.SavedSession | None
        self.restore_stats = None  # core.scanner.RestoreStats | None
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        # QThread.run()에서 예외가 그대로 새어나가면 finished_scan이 영영 발생하지
        # 않아서, 진행 화면이 에러 한 줄 없이 멈춘 채로 남는다(사용자에겐 "응답
        # 없음"으로 보임). gui/single_ai_action.py::_Worker와 같은 패턴으로,
        # 실패도 반드시 신호 하나로 끝나게 한다. (2026-09-11 리뷰)
        try:
            saved = load_session(self.paths) if self.use_saved_session else None
            if saved is not None:
                result, remaining_paths, stats = scan_paths_incremental(
                    self.paths,
                    saved.files,
                    recursive=True,
                    progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
                    should_cancel=lambda: self._cancel_requested,
                    on_heavy_format=self.heavy_format_detected.emit,
                )
                saved.remap_paths(stats.moved)
                saved.drop_categories(stats.changed_paths)
                self.saved_session = saved
                self.restore_stats = stats
            else:
                result, remaining_paths = scan_paths(
                    self.paths,
                    recursive=True,
                    progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
                    should_cancel=lambda: self._cancel_requested,
                    on_heavy_format=self.heavy_format_detected.emit,
                )
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.finished_scan.emit(result, self._cancel_requested, remaining_paths)


class ScanningScreen(QWidget):
    scan_finished = Signal(object, bool, int, list)  # ScanResult, cancelled, planned_total, remaining_paths
    scan_failed = Signal(str)  # 검사가 예상 못한 오류로 끝난 경우 (ScanWorker.failed 참고)

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

        # HEIC/HEIF는 디코딩이 훨씬 무거워서(PRD_MVP우선순위.md 갭 #8 실측: JPEG
        # 대비 10배 이상) 검사 중 처음 발견되면 왜 오래 걸리는지 안내한다.
        self.heavy_format_label = QLabel(
            "HEIC 사진이 포함되어 있어 검사가 더 오래 걸릴 수 있어요."
        )
        self.heavy_format_label.setWordWrap(True)
        self.heavy_format_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        self.heavy_format_label.setVisible(False)
        card_layout.addWidget(self.heavy_format_label)

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

    def start_scan(self, paths: list[str], use_saved_session: bool = False):
        # use_saved_session: 같은 폴더의 저장된 작업이 있으면 불러와서 바뀐
        # 사진만 검사한다(core/session_store.py). 진행률은 "새로 분석할 사진"
        # 기준이라 저장본이 있으면 전체 사진 수보다 훨씬 작은 수로 보인다.
        self.title_label.setText(
            "이전 작업을 확인하고 바뀐 사진만 검사 중..." if use_saved_session else "사진 검사 중..."
        )
        self.progress_bar.setValue(0)
        self.count_label.setText("0 / 0")
        self.current_file_label.setText("현재 검사: -")
        self.eta_label.setText("예상 남은 시간: 계산 중...")
        self.heavy_format_label.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("취소")
        self._planned_total = 0

        self._start_time = time.time()
        self._timer.start()

        self.worker = ScanWorker(paths, use_saved_session=use_saved_session)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_scan.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.heavy_format_detected.connect(self._on_heavy_format_detected)
        self.worker.start()

    def _on_heavy_format_detected(self):
        self.heavy_format_label.setVisible(True)

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
        # 진행률의 total은 "이번에 새로 분석할 사진 수"라서(저장된 작업을 불러온
        # 경우 재사용한 사진은 빠져 있다) 전체 계획 수는 결과에서 다시 구한다.
        planned_total = result.total + len(remaining_paths)
        self.scan_finished.emit(result, cancelled, planned_total, remaining_paths)

    def _on_failed(self, message: str):
        self._timer.stop()
        self.cancel_btn.setEnabled(False)
        self.scan_failed.emit(message)

    def _on_cancel(self):
        if self.worker:
            self.worker.cancel()
        # 화면 전환은 워커가 실제로 멈추고 finished_scan을 보내온 뒤에만 한다
        # (즉시 전환하면 뒤늦게 도착하는 finished_scan이 화면을 다시 덮어써버리는 문제가 있었음)
        self.title_label.setText("취소하는 중...")
        self.current_file_label.setText("현재까지 검사한 내용을 정리하고 있습니다...")
        self.cancel_btn.setEnabled(False)
