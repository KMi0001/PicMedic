"""
gui/main_window.py

PRD 28장 "사용자 플로우" 전체를 QStackedWidget으로 연결한다.

폴더 선택 -> 스캔 -> 결과 -> (상세) -> 복구 -> 복구 결과 -> 결과로 복귀
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QMessageBox

from gui.theme import APP_STYLESHEET
from gui.home_screen import HomeScreen
from gui.scanning_screen import ScanningScreen
from gui.result_screen import ResultScreen
from gui.detail_screen import DetailScreen
from gui.recovery_screen import RecoveryScreen
from gui.recovery_result_screen import RecoveryResultScreen
from models.file_info import FileStatus


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PicMedic — 사진 진단 · 복구 · 정리")
        self.resize(760, 600)
        self.setStyleSheet(APP_STYLESHEET)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_screen = HomeScreen()
        self.scanning_screen = ScanningScreen()
        self.result_screen = ResultScreen()
        self.detail_screen = DetailScreen()
        self.recovery_screen = RecoveryScreen()
        self.recovery_result_screen = RecoveryResultScreen()

        self._current_scan_paths: list[str] = []   # 이번에 core에 실제로 넘긴 경로(최초 스캔 or 이어서 검사용 나머지)
        self._scan_origin_paths: list[str] = []    # '최근 검사'에 기록할 때 쓸 원래 선택 경로
        self._resume_base_result = None             # 이어서 검사 중이면: 이전까지 누적된 결과
        self._resume_base_planned_total = 0          # 이어서 검사 중이면: 원래 전체 계획 파일 수
        self._pending_remaining_paths: list[str] | None = None  # 현재 결과 화면에서 '이어서 검사' 가능한 나머지 파일
        self._pending_planned_total = 0

        for screen in (
            self.home_screen,
            self.scanning_screen,
            self.result_screen,
            self.detail_screen,
            self.recovery_screen,
            self.recovery_result_screen,
        ):
            self.stack.addWidget(screen)

        self._wire_signals()
        self.stack.setCurrentWidget(self.home_screen)

    def _wire_signals(self):
        # Home -> Scanning
        self.home_screen.paths_chosen.connect(self._start_scan)

        # Scanning -> Result / Home (완료·취소 모두 이 신호 하나로 들어옴)
        self.scanning_screen.scan_finished.connect(self._on_scan_finished)

        # Result -> Detail / Recovery / Home(재검사)
        self.result_screen.file_selected.connect(self._open_detail)
        self.result_screen.recovery_requested.connect(lambda files: self._open_recovery(files, None))
        self.result_screen.rescan_requested.connect(lambda: self.stack.setCurrentWidget(self.home_screen))
        self.result_screen.resume_requested.connect(self._on_resume_requested)

        # Detail -> Result / Recovery
        self.detail_screen.back_requested.connect(lambda: self.stack.setCurrentWidget(self.result_screen))
        self.detail_screen.recover_requested.connect(self._open_recovery)

        # Recovery -> Result / RecoveryResult
        self.recovery_screen.back_requested.connect(lambda: self.stack.setCurrentWidget(self.result_screen))
        self.recovery_screen.recovery_finished.connect(self._on_recovery_finished)

        # RecoveryResult -> Result
        self.recovery_result_screen.done_requested.connect(
            lambda: self.stack.setCurrentWidget(self.result_screen)
        )

    # --- 화면 전환 핸들러 ------------------------------------------------

    def _start_scan(self, paths: list):
        self._current_scan_paths = paths
        self._scan_origin_paths = paths
        self._resume_base_result = None
        self._resume_base_planned_total = 0
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
                QMessageBox.information(self, "PicMedic", "이미지 파일이 없습니다.")
            self.stack.setCurrentWidget(self.home_screen)
        else:
            # '이어서 검사' 버튼이 다음에 눌렸을 때 쓸 수 있도록 현재 상태를 기억해둔다
            self._pending_remaining_paths = remaining_paths if cancelled else None
            self._pending_planned_total = planned_total
            self.result_screen.set_result(
                result, cancelled=cancelled, planned_total=planned_total, remaining_paths=remaining_paths
            )
            self.stack.setCurrentWidget(self.result_screen)

    def _open_detail(self, info):
        self.detail_screen.set_file(info)
        self.stack.setCurrentWidget(self.detail_screen)

    def _open_recovery(self, files, mode):
        self.recovery_screen.set_files(files, preselected_mode=mode)
        self.stack.setCurrentWidget(self.recovery_screen)

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
