"""
gui/scan_session_window.py

스캔 1회를 처음부터 끝까지 담당하는 독립 창.
검사 진행 -> 검사 결과 -> (상세) -> 복구 -> 복구 결과 -> 결과로 복귀, 를 이 창 하나 안에서
QStackedWidget으로 전환한다 (예전엔 gui/main_window.py가 이 전체를 앱 전체 싱글턴
화면들로 관리했음). gui/main_window.py는 파일/폴더를 선택할 때마다 이 창을 새로
띄우기만 해서, 여러 폴더를 동시에 검사할 수 있다 (PRD_MVP우선순위.md 갭 #10).

"최근 검사" 목록(HomeScreen)만 세션과 무관하게 전역으로 공유되므로, home_screen을
생성자에서 받아 그대로 쓴다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QStackedWidget, QVBoxLayout

from gui.common_dialogs import info_dialog as _info_dialog
from gui.scanning_screen import ScanningScreen
from gui.result_screen import ResultScreen
from gui.detail_screen import DetailScreen
from gui.recovery_screen import RecoveryScreen
from gui.recovery_result_screen import RecoveryResultScreen
from gui.duplicate_screen import DuplicateScreen
from gui.trash_screen import TrashScreen
from models.file_info import FileStatus


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


class ScanSessionWindow(QWidget):
    """스캔 1회 = 창 1개. 부모(MainWindow)에 얹혀서 스타일시트를 물려받으면서도
    Qt.Window 플래그로 독립된 최상위 창(제목표시줄, 자체 X 버튼)으로 뜬다."""

    closed = Signal(object)  # self — main_window가 세션 목록에서 정리하도록

    # 검사 진행 중엔 카드 하나 크기(ScanningScreen.sizeHint() 기준)에 맞춰 작게,
    # 결과가 나오면 표를 보기 편하게 크게 — 검사 중일 때 흰 카드 하나만 있는데
    # 창이 크면 주변 여백만 넓어 보여서 "팝업" 느낌이 안 살던 문제를 고친다.
    _SCANNING_SIZE = (600, 440)
    _NORMAL_SIZE = (760, 600)

    def __init__(self, home_screen, paths: list[str], parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.home_screen = home_screen
        self.setWindowTitle("PicMedic — 사진 진단 · 복구 · 정리")
        self.resize(*self._SCANNING_SIZE)

        self.stack = _CurrentOnlyStack()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)

        self.scanning_screen = ScanningScreen()
        self.result_screen = ResultScreen()
        self.detail_screen = DetailScreen()
        self.recovery_screen = RecoveryScreen()
        self.recovery_result_screen = RecoveryResultScreen()
        self.duplicate_screen = DuplicateScreen()
        self.trash_screen = TrashScreen()

        for screen in (
            self.scanning_screen,
            self.result_screen,
            self.detail_screen,
            self.recovery_screen,
            self.recovery_result_screen,
            self.duplicate_screen,
            self.trash_screen,
        ):
            self.stack.addWidget(screen)

        self._current_scan_paths: list[str] = []   # 이번에 core에 실제로 넘긴 경로(최초 스캔 or 이어서 검사용 나머지)
        self._scan_origin_paths: list[str] = []    # '최근 검사'에 기록할 때 쓸 원래 선택 경로
        self._resume_base_result = None             # 이어서 검사 중이면: 이전까지 누적된 결과
        self._resume_base_planned_total = 0          # 이어서 검사 중이면: 원래 전체 계획 파일 수
        self._pending_remaining_paths: list[str] | None = None  # 현재 결과 화면에서 '이어서 검사' 가능한 나머지 파일
        self._pending_planned_total = 0
        self._detail_return_screen = self.result_screen  # 상세보기 뒤로가기 시 돌아갈 화면(연 곳에 따라 다름)

        self._wire_signals()
        self.stack.setCurrentWidget(self.scanning_screen)
        self._start_scan(paths)

    def _wire_signals(self):
        # Scanning -> Result / (홈으로)
        self.scanning_screen.scan_finished.connect(self._on_scan_finished)

        # Result -> Detail / Recovery / 홈 / 중복 사진
        self.result_screen.file_selected.connect(self._open_detail)
        self.result_screen.recovery_requested.connect(lambda files: self._open_recovery(files, None))
        self.result_screen.rescan_requested.connect(self._go_home)
        self.result_screen.resume_requested.connect(self._on_resume_requested)
        self.result_screen.duplicates_requested.connect(self._open_duplicates)

        # 중복 사진 -> 결과 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.duplicate_screen.back_requested.connect(lambda: self.stack.setCurrentWidget(self.result_screen))
        self.duplicate_screen.view_trash_requested.connect(self._open_trash)
        self.duplicate_screen.file_selected.connect(
            lambda info: self._open_detail(info, return_to=self.duplicate_screen)
        )

        # 임시 휴지통 -> 중복 사진 (남은 중복이 없으면 빈 화면 대신 검사 결과로)
        self.trash_screen.back_requested.connect(self._back_from_trash)

        # Detail -> 열었던 화면(결과 또는 중복 사진) / Recovery
        self.detail_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self._detail_return_screen)
        )
        self.detail_screen.recover_requested.connect(self._open_recovery)

        # Recovery -> Result / RecoveryResult
        self.recovery_screen.back_requested.connect(lambda: self.stack.setCurrentWidget(self.result_screen))
        self.recovery_screen.recovery_finished.connect(self._on_recovery_finished)

        # RecoveryResult -> Result
        self.recovery_result_screen.done_requested.connect(
            lambda: self.stack.setCurrentWidget(self.result_screen)
        )

    # --- 화면 전환 핸들러 ------------------------------------------------

    def _go_home(self):
        # "홈" 버튼(구 "다시 검사") — 홈 화면은 MainWindow 쪽에 항상 떠 있으므로
        # 이 세션 창은 그냥 닫기만 하면 된다.
        self.close()

    def _start_scan(self, paths: list):
        self._current_scan_paths = paths
        self._scan_origin_paths = paths
        self._resume_base_result = None
        self._resume_base_planned_total = 0
        self.resize(*self._SCANNING_SIZE)
        self.stack.setCurrentWidget(self.scanning_screen)
        self.scanning_screen.start_scan(paths)

    def _on_resume_requested(self):
        """검사 결과 화면의 '이어서 검사' 버튼 — 나머지 파일만 마저 스캔한다."""
        if self._pending_remaining_paths is None or self.result_screen.result is None:
            return
        self._resume_base_result = self.result_screen.result
        self._resume_base_planned_total = self._pending_planned_total
        self._current_scan_paths = self._pending_remaining_paths
        # _scan_origin_paths는 그대로 유지 (최근 검사 목록엔 원래 선택했던 경로로 남아야 하므로)
        self.resize(*self._SCANNING_SIZE)
        self.stack.setCurrentWidget(self.scanning_screen)
        self.scanning_screen.start_scan(self._current_scan_paths)

    def _on_scan_finished(self, result, cancelled: bool, planned_total: int, remaining_paths: list):
        if self._resume_base_result is not None:
            result = self._resume_base_result.merge(result)
            planned_total = self._resume_base_planned_total or planned_total
            self._resume_base_result = None
            self._resume_base_planned_total = 0

        self.home_screen.record_scan_outcome(self._scan_origin_paths, result, cancelled, planned_total)

        if result.total == 0:
            if not cancelled:
                _info_dialog(self, "이미지 파일이 없습니다.")
            self.close()
        else:
            # '이어서 검사' 버튼이 다음에 눌렸을 때 쓸 수 있도록 현재 상태를 기억해둔다
            self._pending_remaining_paths = remaining_paths if cancelled else None
            self._pending_planned_total = planned_total
            self.result_screen.set_result(
                result, cancelled=cancelled, planned_total=planned_total, remaining_paths=remaining_paths
            )
            # 중복 화면은 그룹이 수백 개면 카드를 그만큼 만들어야 해서 스캔 하나
            # 끝날 때마다 미리 만들어두면(당장 보지도 않는데) 그때마다 응답 없음이
            # 뜬다 — 사용자가 "중복 파일 보기"를 실제로 눌렀을 때만 만든다
            # (_open_duplicates 참고).
            self.resize(*self._NORMAL_SIZE)
            self.stack.setCurrentWidget(self.result_screen)

    def _open_detail(self, info, return_to=None):
        self._detail_return_screen = return_to or self.result_screen
        self.detail_screen.set_file(info)
        self.stack.setCurrentWidget(self.detail_screen)

    def _open_recovery(self, files, mode):
        self.recovery_screen.set_files(files, preselected_mode=mode)
        self.stack.setCurrentWidget(self.recovery_screen)

    def _open_duplicates(self):
        result = self.result_screen.result
        if not result or not result.duplicate_groups():
            # 처리할 중복이 아예 없으면 빈 화면을 보여줄 필요 없이 검사 결과로
            # 바로 돌아간다.
            _info_dialog(self, "중복된 파일이 없습니다.")
            return
        self.duplicate_screen.set_result(result)
        self.stack.setCurrentWidget(self.duplicate_screen)

    def _open_trash(self):
        self.trash_screen.refresh()
        self.stack.setCurrentWidget(self.trash_screen)

    def _back_from_trash(self):
        if self.duplicate_screen.has_pending():
            self.stack.setCurrentWidget(self.duplicate_screen)
        else:
            self.stack.setCurrentWidget(self.result_screen)

    def _on_recovery_finished(self, outcomes, output_dir):
        if self.result_screen.result is not None:
            for outcome in outcomes:
                # 원래 '정상'이던 파일은 복구가 아니라 단순 변환이므로 상태를 바꾸지 않는다
                if outcome.success and outcome.original.status != FileStatus.NORMAL:
                    self.result_screen.result.mark_recovered(outcome.original)
            self.result_screen.refresh_current_result()

        # 이번 복구가 어느 '최근 검사' 항목에서 시작됐는지는 _scan_origin_paths로 알 수 있다
        # (검사 결과 화면에서 왔든 상세 화면에서 왔든, 새 스캔을 시작하기 전까지는 유지됨).
        self.home_screen.record_recovery_outcome(self._scan_origin_paths, outcomes, output_dir)

        self.recovery_result_screen.set_outcomes(outcomes, output_dir)
        self.stack.setCurrentWidget(self.recovery_result_screen)

    # --- 창 종료 ---------------------------------------------------------

    def closeEvent(self, event):
        # 검사/복구가 백그라운드 스레드로 아직 도는 중에 창을 지워버리면
        # ("QThread: Destroyed while thread is still running") 죽는다 — 각 화면의
        # 취소 버튼으로 스레드가 실제로 끝난 뒤에만 닫히게 막는다.
        scan_worker = getattr(self.scanning_screen, "worker", None)
        recovery_worker = getattr(self.recovery_screen, "worker", None)
        if (scan_worker is not None and scan_worker.isRunning()) or (
            recovery_worker is not None and recovery_worker.isRunning()
        ):
            event.ignore()
            return
        self.closed.emit(self)
        super().closeEvent(event)
