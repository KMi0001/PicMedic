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

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QWidget, QStackedWidget, QVBoxLayout

from core.date_organizer import organize_by_date
from gui.common_dialogs import (
    confirm_dialog as _confirm_dialog,
    info_dialog as _info_dialog,
    info_dialog_with_folder as _info_dialog_with_folder,
    ProgressDialog,
)
from gui.scanning_screen import ScanningScreen
from gui.result_screen import ResultScreen
from gui.detail_screen import DetailScreen
from gui.recovery_screen import RecoveryScreen
from gui.recovery_result_screen import RecoveryResultScreen
from gui.duplicate_screen import DuplicateScreen
from gui.similar_screen import SimilarScreen
from gui.date_organize_screen import DateOrganizeScreen
from gui.date_group_detail_screen import DateGroupDetailScreen
from gui.trash_screen import TrashScreen
from models.file_info import FileStatus


class _DateOrganizeWorker(QThread):
    """core/date_organizer.py::organize_by_date()는 사진이 많으면 수백 개 파일을
    복사/이동하느라 시간이 걸릴 수 있어서, gui/recovery_screen.py::RecoveryWorker와
    같은 이유로 별도 스레드에서 돌린다."""

    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[core.date_organizer.OrganizeOutcome]

    def __init__(self, groups, mode: str, output_root: str, granularity: str, parent=None):
        super().__init__(parent)
        self.groups = groups
        self.mode = mode
        self.output_root = output_root
        self.granularity = granularity
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        outcomes = organize_by_date(
            self.groups,
            self.mode,
            self.output_root,
            granularity=self.granularity,
            progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
            should_cancel=lambda: self._cancel_requested,
        )
        self.finished_batch.emit(outcomes)


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
    # 날짜별 정리는 그룹 카드(썸네일 줄 포함)를 최소 3개는 스크롤 없이 보여줘야
    # 해서, 다른 화면들보다 세로로 더 크게 잡는다.
    _DATE_ORGANIZE_SIZE = (760, 820)

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
        self.similar_screen = SimilarScreen()
        self.date_organize_screen = DateOrganizeScreen()
        self.date_group_detail_screen = DateGroupDetailScreen()
        self.trash_screen = TrashScreen()
        self.date_organize_progress_dialog = ProgressDialog(self)
        self.date_organize_progress_dialog.cancel_requested.connect(self._on_date_organize_cancel_requested)
        self._date_organize_worker: _DateOrganizeWorker | None = None

        for screen in (
            self.scanning_screen,
            self.result_screen,
            self.detail_screen,
            self.recovery_screen,
            self.recovery_result_screen,
            self.duplicate_screen,
            self.similar_screen,
            self.date_organize_screen,
            self.date_group_detail_screen,
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
        self._trash_return_screen = self.result_screen  # 임시휴지통 뒤로가기 시 돌아갈 화면(연 곳에 따라 다름)

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
        self.result_screen.similar_requested.connect(self._open_similar)
        self.result_screen.date_organize_requested.connect(self._open_date_organize)

        # 중복 사진 -> 결과 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.duplicate_screen.back_requested.connect(self._back_from_duplicates)
        self.duplicate_screen.view_trash_requested.connect(lambda: self._open_trash(self.duplicate_screen))
        self.duplicate_screen.file_selected.connect(
            lambda info: self._open_detail(info, return_to=self.duplicate_screen)
        )

        # 유사 사진 -> 결과 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.similar_screen.back_requested.connect(self._back_from_similar)
        self.similar_screen.view_trash_requested.connect(lambda: self._open_trash(self.similar_screen))
        self.similar_screen.file_selected.connect(
            lambda info: self._open_detail(info, return_to=self.similar_screen)
        )

        # 날짜별 정리 -> 결과 / 그룹 상세(사진 확인)
        self.date_organize_screen.back_requested.connect(self._back_from_date_organize)
        self.date_organize_screen.organize_requested.connect(self._on_date_organize_requested)
        self.date_organize_screen.group_opened.connect(self._open_date_group_detail)

        # 그룹 상세 -> 날짜별 정리
        self.date_group_detail_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self.date_organize_screen)
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

    def _back_from_duplicates(self):
        # duplicate_screen이 "정리 실행"으로 이미 self.result_screen.result(같은
        # ScanResult 객체)에서 파일을 뺐어도(ScanResult.remove), 검사 결과 화면의
        # 표/칩은 따로 다시 그려주지 않으면 그대로 갱신 안 된 채 남는다 — 휴지통에
        # 옮긴 사진이 검사 결과 목록에 계속 보이던 문제.
        self.result_screen.refresh_current_result()
        self.stack.setCurrentWidget(self.result_screen)

    def _back_from_similar(self):
        self.result_screen.refresh_current_result()
        self.stack.setCurrentWidget(self.result_screen)

    def _open_duplicates(self):
        result = self.result_screen.result
        if not result or not result.duplicate_groups():
            # 처리할 중복이 아예 없으면 빈 화면을 보여줄 필요 없이 검사 결과로
            # 바로 돌아간다.
            _info_dialog(self, "중복된 파일이 없습니다.")
            return
        self.duplicate_screen.set_result(result)
        self.stack.setCurrentWidget(self.duplicate_screen)

    def _open_similar(self):
        result = self.result_screen.result
        if not result or not result.files:
            _info_dialog(self, "정리할 사진이 없습니다.")
            return
        # similar_groups() 계산 자체가 느릴 수 있어(퍼셉추얼 해시 쌍 비교) 여기서
        # 미리 확인하지 않고, SimilarScreen이 백그라운드로 계산하는 동안 진행률
        # 팝업을 보여준다 — 결과가 없으면 화면 자체가 빈 상태를 보여준다.
        self.similar_screen.set_result(result)
        self.stack.setCurrentWidget(self.similar_screen)

    def _open_date_organize(self):
        result = self.result_screen.result
        if not result or not result.files:
            _info_dialog(self, "정리할 사진이 없습니다.")
            return

        origin = Path(self._scan_origin_paths[0]) if self._scan_origin_paths else Path.cwd()
        base_dir = origin if origin.is_dir() else origin.parent

        self.date_organize_screen.set_result(result)
        self.date_organize_screen.set_output_root(str(base_dir / "날짜별_정리"))
        self.resize(*self._DATE_ORGANIZE_SIZE)
        self.stack.setCurrentWidget(self.date_organize_screen)

    def _back_from_date_organize(self):
        self.resize(*self._NORMAL_SIZE)
        self.stack.setCurrentWidget(self.result_screen)

    def _open_date_group_detail(self, label: str, files: list):
        self.date_group_detail_screen.set_group(label, files)
        self.stack.setCurrentWidget(self.date_group_detail_screen)

    def _on_date_organize_requested(self, mode: str):
        if self._date_organize_worker is not None:
            return

        if mode == "move":
            confirmed = _confirm_dialog(
                self,
                "이동을 선택하셨어요.<br><br>"
                "원본 파일이 새 폴더로 옮겨지고 원래 위치에는 남지 않아요.<br>"
                "계속할까요?",
                confirm_text="이동 시작",
                cancel_text="취소",
            )
            if not confirmed:
                return

        groups = self.date_organize_screen.groups()
        output_root = self.date_organize_screen.output_root()
        granularity = self.date_organize_screen.granularity()

        self._date_organize_worker = _DateOrganizeWorker(groups, mode, output_root, granularity, self)
        self._date_organize_worker.progress.connect(self._on_date_organize_progress)
        self._date_organize_worker.finished_batch.connect(self._on_date_organize_finished)

        title = "이동하는 중" if mode == "move" else "복사하는 중"
        self.date_organize_progress_dialog.start(title)
        self._date_organize_worker.start()
        self.date_organize_progress_dialog.exec()

    def _on_date_organize_progress(self, current: int, total: int, filename: str):
        self.date_organize_progress_dialog.update_progress(current, total, filename)

    def _on_date_organize_cancel_requested(self):
        if self._date_organize_worker is not None:
            self._date_organize_worker.cancel()

    def _on_date_organize_finished(self, outcomes):
        self.date_organize_progress_dialog.accept()
        worker = self._date_organize_worker
        self._date_organize_worker = None
        if worker is not None:
            worker.wait()

        # "이미 있어서 건너뜀"(core/date_organizer.py::_already_organized)은 실제로
        # 옮기거나 복사한 게 아니므로 newly_done과 분리해서 센다 — 이동 모드에서
        # 특히 중요: 건너뛴 파일은 원본을 일부러 그대로 뒀으니(안전한 선택),
        # 검사 결과 목록에서도 빼면 안 된다(빼면 아직 안 옮겨진 파일이 사라진
        # 유령 항목이 됨).
        newly_done = [o for o in outcomes if o.success and not o.skipped]
        skipped = [o for o in outcomes if o.skipped]
        failed = [o for o in outcomes if not o.success]

        if worker is not None and worker.mode == "move" and self.result_screen.result is not None:
            for outcome in newly_done:
                self.result_screen.result.remove(outcome.original)
            self.result_screen.refresh_current_result()

        output_root = worker.output_root if worker is not None else self.date_organize_screen.output_root()

        lines = [f"{len(newly_done)}개 정리했습니다."]
        if skipped:
            lines.append(f"{len(skipped)}개는 이미 있어서 건너뛰었습니다.")
        if failed:
            lines.append(f"{len(failed)}개는 실패했습니다:")
            lines.extend(f"{o.original.filename} ({o.error_message})" for o in failed[:5])

        _info_dialog_with_folder(self, "\n".join(lines), output_root)

        self.resize(*self._NORMAL_SIZE)
        self.stack.setCurrentWidget(self.result_screen)

    def _open_trash(self, return_to=None):
        self._trash_return_screen = return_to or self.result_screen
        self.trash_screen.refresh()
        self.stack.setCurrentWidget(self.trash_screen)

    def _back_from_trash(self):
        if self._trash_return_screen is self.similar_screen and self.similar_screen.has_pending():
            self.stack.setCurrentWidget(self.similar_screen)
        elif self.duplicate_screen.has_pending():
            self.stack.setCurrentWidget(self.duplicate_screen)
        else:
            # 더 처리할 그룹이 없어 검사 결과로 바로 돌아가는 경우 — 그동안
            # 중복/유사 정리로 빠진 파일들이 표/칩에 반영되게 새로고침한다.
            self.result_screen.refresh_current_result()
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
        if (
            (scan_worker is not None and scan_worker.isRunning())
            or (recovery_worker is not None and recovery_worker.isRunning())
            or (self._date_organize_worker is not None and self._date_organize_worker.isRunning())
        ):
            event.ignore()
            return
        self.closed.emit(self)
        super().closeEvent(event)
