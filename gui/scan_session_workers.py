"""
gui/scan_session_workers.py

gui/scan_session_window.py::ScanSessionWindow이 쓰는 백그라운드 워커(QThread)와
보조 위젯. ScanSessionWindow 자체와 달리 화면 전환 로직이 없는 순수 실행 단위라
따로 뺐다.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QStackedWidget

from core.scanner import list_image_files


class _OrganizeWorker(QThread):
    """core/date_organizer.py::organize_by_date()/organize_by_city()는 사진이
    많으면 수백 개 파일을 복사/이동하느라 시간이 걸릴 수 있어서,
    gui/recovery_screen.py::RecoveryWorker와 같은 이유로 별도 스레드에서
    돌린다. 날짜별/도시별 둘 다 이 워커를 쓰고, 실제 실행 함수(run_fn)만
    호출부(gui/scan_session_organize_mixin.py의 _on_date_organize_requested/
    _on_city_organize_requested)가 다르게 준비해 넘긴다."""

    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[core.date_organizer.OrganizeOutcome]
    failed = Signal(str)  # 예상 못한 예외 (아래 run() 참고)

    def __init__(self, run_fn, mode: str, output_root: str, parent=None):
        super().__init__(parent)
        self._run_fn = run_fn
        self.mode = mode
        self.output_root = output_root
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        # gui/recovery_screen.py::RecoveryWorker.run과 같은 이유 — 예외가 새어나가면
        # finished_batch가 안 와서 모달 진행 팝업(organize_progress_dialog)이 영영
        # 닫히지 않는다. (2026-09-11 리뷰)
        try:
            outcomes = self._run_fn(
                progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.finished_batch.emit(outcomes)


class _LightListWorker(QThread):
    """"정리 > 고양이 찾기" 빠른 경로 전용(2026-09-10) — core/scanner.py::
    list_image_files()로 파일 목록만 가볍게 모은다(손상 검사·해시 없음).
    폴더 순회 자체도 사진이 수만 장이면 잠깐 걸릴 수 있어(디스크 I/O) 별도
    스레드에서 돈다 — 매 파일 진단하는 무거운 스캔보다는 훨씬 빠르지만
    "즉시"는 아님."""

    finished_listing = Signal(object)  # ScanResult (가벼운 FileInfo만 채워짐)
    failed = Signal(str)  # 예상 못한 예외 (아래 run() 참고)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        # _OrganizeWorker.run과 같은 이유 — 실패해도 반드시 신호 하나로 끝나야
        # light_scan_progress_dialog(모달)가 닫힌다. (2026-09-11 리뷰)
        try:
            result = list_image_files(self._paths, should_cancel=lambda: self._cancel_requested)
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.finished_listing.emit(result)


class _CurrentOnlyStack(QStackedWidget):
    """일반 QStackedWidget은 minimumSizeHint()가 담고 있는 모든 페이지 중 가장 큰
    값을 기준으로 잡아서, 화면이 5개(검사/결과/상세/복구/복구결과)나 들어있는 이
    창은 검사 화면만 보여줄 때도 제일 큰 페이지(결과 화면 표)만큼 최소 크기가
    묶여버린다 — ScanSessionWindow.resize()로 작게 줄여도 그 아래로는 안 줄어듦.
    지금 보이는 페이지의 크기만 반영하도록 오버라이드해서 이 묶임을 푼다."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()
