"""
gui/scan_session_window.py

스캔 1회를 처음부터 끝까지 담당하는 독립 창.
검사 진행 -> 검사 결과 -> (상세) -> 복구 -> 복구 결과 -> 결과로 복귀, 를 이 창 하나 안에서
QStackedWidget으로 전환한다 (예전엔 gui/main_window.py가 이 전체를 앱 전체 싱글턴
화면들로 관리했음). gui/main_window.py는 파일/폴더를 선택할 때마다 이 창을 새로
띄우기만 해서, 여러 폴더를 동시에 검사할 수 있다 (PRD_MVP우선순위.md 갭 #10).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QWidget, QStackedWidget, QVBoxLayout

from core.date_organizer import organize_by_city, organize_by_date, organize_cat_finder_results
from core.scanner import list_image_files
from gui.common_dialogs import (
    confirm_dialog as _confirm_dialog,
    info_dialog as _info_dialog,
    info_dialog_with_folder as _info_dialog_with_folder,
    ProgressDialog,
)
from gui.scanning_screen import ScanningScreen
from gui.result_screen import ResultScreen
from gui.theme import APP_STYLESHEET
from gui.detail_screen import DetailScreen
from gui.recovery_screen import RecoveryScreen
from gui.recovery_result_screen import RecoveryResultScreen
from gui.duplicate_screen import DuplicateScreen
from gui.similar_screen import SimilarScreen
from gui.date_organize_screen import DateOrganizeScreen
from gui.organize_hub_screen import OrganizeHubScreen
from gui.city_organize_screen import CityOrganizeScreen
from gui.date_group_detail_screen import DateGroupDetailScreen
from gui.trash_screen import TrashScreen
from gui.cat_finder_screen import CatFinderScreen
from models.file_info import FileStatus
from utils import trash


class _OrganizeWorker(QThread):
    """core/date_organizer.py::organize_by_date()/organize_by_city()는 사진이
    많으면 수백 개 파일을 복사/이동하느라 시간이 걸릴 수 있어서,
    gui/recovery_screen.py::RecoveryWorker와 같은 이유로 별도 스레드에서
    돌린다. 날짜별/도시별 둘 다 이 워커를 쓰고, 실제 실행 함수(run_fn)만
    호출부(gui/scan_session_window.py의 _on_date_organize_requested/
    _on_city_organize_requested)가 다르게 준비해 넘긴다."""

    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[core.date_organizer.OrganizeOutcome]

    def __init__(self, run_fn, mode: str, output_root: str, parent=None):
        super().__init__(parent)
        self._run_fn = run_fn
        self.mode = mode
        self.output_root = output_root
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        outcomes = self._run_fn(
            progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
            should_cancel=lambda: self._cancel_requested,
        )
        self.finished_batch.emit(outcomes)


class _LightListWorker(QThread):
    """"정리 > 고양이 찾기" 빠른 경로 전용(2026-09-10) — core/scanner.py::
    list_image_files()로 파일 목록만 가볍게 모은다(손상 검사·해시 없음).
    폴더 순회 자체도 사진이 수만 장이면 잠깐 걸릴 수 있어(디스크 I/O) 별도
    스레드에서 돈다 — 매 파일 진단하는 무거운 스캔보다는 훨씬 빠르지만
    "즉시"는 아님."""

    finished_listing = Signal(object)  # ScanResult (가벼운 FileInfo만 채워짐)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        result = list_image_files(self._paths, should_cancel=lambda: self._cancel_requested)
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


class ScanSessionWindow(QWidget):
    """스캔 1회 = 창 1개. Qt 부모 없이 완전히 독립된 최상위 창(제목표시줄, 자체
    X 버튼)으로 뜬다 — 예전엔 parent=MainWindow로 만들어서 스타일시트만 물려받고
    Qt.Window로 독립된 창처럼 보이게 했었는데, Windows에서 "부모가 있는
    Qt.Window"는 최대화는 되지만 테두리를 드래그해 리사이즈하는 게 안 먹는 문제가
    있어서(2026-09-08, 사용자 리포트) parent 없이 띄우고 스타일시트는 직접
    적용하는 방식으로 바꿨다. 그 대신 MainWindow가 자동으로 이 창들을 닫아주지
    않으므로 MainWindow.closeEvent()에서 열려있는 세션 창을 직접 닫아준다
    (gui/main_window.py 참고)."""

    closed = Signal(object)  # self — main_window가 세션 목록에서 정리하도록

    # 검사 진행 중엔 카드 하나 크기(ScanningScreen.sizeHint() 기준)에 맞춰 작게,
    # 결과가 나오면 화면을 넓게 쓰는 큰 창으로 — 검사 중일 때 흰 카드 하나만 있는데
    # 창이 크면 주변 여백만 넓어 보여서 "팝업" 느낌이 안 살던 문제를 고친다.
    #
    # 결과 화면부터는(표/썸네일 그리드/지도 등 내용이 많은 화면들) 화면을 넓게 쓰는
    # 쪽이 낫고, 이 화면들 사이를 오갈 때(뒤로가기, 정리 완료 등) 마다 창을 작게
    # 줄였다 다시 키우면 — 특히 리사이즈와 화면 전환이 같은 순간에 겹치면 — Windows
    # 컴포지터가 이전 화면 픽셀을 완전히 지우지 못하고 잔상처럼 남기는 문제가 있었다.
    # 그래서 결과 화면 이후로는 창 크기를 한 번(검사 끝나고 커질 때) 말고는 절대
    # 다시 건드리지 않는다 — 화면이 바뀌어도 창 크기는 고정, 사용자가 직접 드래그해
    # 조절하는 것만 반영된다.
    _SCANNING_SIZE = (600, 440)
    _NORMAL_SIZE = (1200, 820)
    _MIN_NORMAL_SIZE = (900, 600)

    def __init__(
        self,
        paths: list[str],
        parent=None,
        land_on_organize: bool = False,
    ):
        super().__init__(parent)
        # gui/home_screen.py의 "정리" 카드로 시작된 세션이면(2026-09-10) 스캔을
        # 바로 돌리지 않고 정리 허브부터 보여준다 — 카드(중복/유사/날짜별/
        # 도시별) 중 하나를 실제로 고를 때만 그때 가서 전체 스캔을 시작한다
        # (_ensure_scanned_then 참고). "고양이 찾기"는 그 스캔과 무관하게
        # 항상 자기만의 가벼운 경로(core/scanner.py::list_image_files, 손상
        # 검사·해시 생략)를 쓴다 — _open_cat_finder 참고.
        self._organize_paths: list[str] | None = None  # land_on_organize일 때만 채워짐 — 카드 클릭 시 스캔에 씀
        self._pending_organize_destination = None  # 스캔이 끝나면 열 화면(콜백) — _ensure_scanned_then
        self.setWindowFlags(Qt.Window)
        self.setStyleSheet(APP_STYLESHEET)
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
        self.organize_hub_screen = OrganizeHubScreen()
        self.duplicate_screen = DuplicateScreen()
        self.similar_screen = SimilarScreen()
        self.date_organize_screen = DateOrganizeScreen()
        self.date_group_detail_screen = DateGroupDetailScreen()
        self.city_organize_screen = CityOrganizeScreen()
        self.cat_finder_screen = CatFinderScreen()
        self.trash_screen = TrashScreen()
        # 날짜별/도시별 "정리하기" 둘 다 같은 진행률 팝업 + 워커를 공유한다
        # (동시에 하나만 실행되므로 화면별로 따로 둘 필요 없음).
        self.organize_progress_dialog = ProgressDialog(self)
        self.organize_progress_dialog.cancel_requested.connect(self._on_organize_cancel_requested)
        self._organize_worker: _OrganizeWorker | None = None

        # 고양이 찾기 빠른 경로 전용 — 위 organize_progress_dialog와
        # 별개 인스턴스인 이유: 저쪽은 진행률(%)이 있는 결정적 작업이라 이쪽에서
        # setRange(0,0)(바쁨 표시, 전체 개수를 미리 모름)으로 바꿔두면 다음에
        # organize_progress_dialog를 쓸 때도 그 range가 남아있을 위험이 있다.
        self.light_scan_progress_dialog = ProgressDialog(self)
        self.light_scan_progress_dialog.cancel_requested.connect(self._on_light_scan_cancel_requested)
        self._light_scan_worker: _LightListWorker | None = None

        for screen in (
            self.scanning_screen,
            self.result_screen,
            self.detail_screen,
            self.recovery_screen,
            self.recovery_result_screen,
            self.organize_hub_screen,
            self.duplicate_screen,
            self.similar_screen,
            self.date_organize_screen,
            self.date_group_detail_screen,
            self.city_organize_screen,
            self.cat_finder_screen,
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
        self._group_detail_return_screen = self.date_organize_screen  # 그룹 상세 뒤로가기 시 돌아갈 화면(날짜별/도시별)

        self._wire_signals()
        if land_on_organize:
            # 스캔 없이 곧장 정리 허브를 보통 크기로 보여준다 — 카드를 실제로
            # 고르기 전까지는 진단 스캔을 아예 시작하지 않는다.
            self._organize_paths = paths
            self._scan_origin_paths = paths
            self.resize(*self._NORMAL_SIZE)
            self.setMinimumSize(*self._MIN_NORMAL_SIZE)
            self.organize_hub_screen.set_result(None)
            self.stack.setCurrentWidget(self.organize_hub_screen)
        else:
            self.stack.setCurrentWidget(self.scanning_screen)
            self._start_scan(paths)

    def _wire_signals(self):
        # Scanning -> Result / (홈으로)
        self.scanning_screen.scan_finished.connect(self._on_scan_finished)

        # Result -> Detail / Recovery / 홈
        self.result_screen.file_selected.connect(self._open_detail)
        self.result_screen.recovery_requested.connect(lambda files: self._open_recovery(files, None))
        self.result_screen.rescan_requested.connect(self._go_home)
        self.result_screen.resume_requested.connect(self._on_resume_requested)

        # 정리 허브 -> 결과 / 중복·유사·날짜별·도시별 각 화면
        self.organize_hub_screen.back_requested.connect(self._back_from_organize_hub)
        self.organize_hub_screen.duplicates_requested.connect(self._open_duplicates)
        self.organize_hub_screen.similar_requested.connect(self._open_similar)
        self.organize_hub_screen.date_organize_requested.connect(self._open_date_organize)
        self.organize_hub_screen.city_organize_requested.connect(self._open_city_organize)
        self.organize_hub_screen.cat_finder_requested.connect(self._open_cat_finder)

        # 고양이 찾기 -> 정리 허브 / 상세보기(사진 미리보기) / "이 방식대로 정리하기"
        self.cat_finder_screen.back_requested.connect(self._back_from_cat_finder)
        self.cat_finder_screen.file_selected.connect(
            lambda info, group: self._open_detail(info, group=group, return_to=self.cat_finder_screen)
        )
        self.cat_finder_screen.organize_requested.connect(self._on_cat_finder_organize_requested)

        # 중복 사진 -> 정리 허브 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.duplicate_screen.back_requested.connect(self._back_from_duplicates)
        self.duplicate_screen.view_trash_requested.connect(
            lambda infos: self._open_trash(self.duplicate_screen, infos)
        )
        self.duplicate_screen.file_selected.connect(
            lambda info, group: self._open_detail(info, group=group, return_to=self.duplicate_screen)
        )

        # 유사 사진 -> 정리 허브 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.similar_screen.back_requested.connect(self._back_from_similar)
        self.similar_screen.view_trash_requested.connect(
            lambda infos: self._open_trash(self.similar_screen, infos)
        )
        self.similar_screen.file_selected.connect(
            lambda info, group: self._open_detail(info, group=group, return_to=self.similar_screen)
        )

        # 날짜별 정리 -> 정리 허브 / 그룹 상세(사진 확인)
        self.date_organize_screen.back_requested.connect(self._back_from_date_organize)
        self.date_organize_screen.organize_requested.connect(self._on_date_organize_requested)
        self.date_organize_screen.group_opened.connect(self._open_date_group_detail)

        # 도시별 정리 -> 정리 허브 / 그룹 상세(사진 확인)
        self.city_organize_screen.back_requested.connect(self._back_from_city_organize)
        self.city_organize_screen.photo_selected.connect(self._open_city_group_detail)
        self.city_organize_screen.organize_requested.connect(self._on_city_organize_requested)

        # 그룹 상세 -> 열었던 화면(날짜별/도시별) / 체크 해제한 제외 목록을 그 화면에 반영
        self.date_group_detail_screen.back_requested.connect(
            lambda: self.stack.setCurrentWidget(self._group_detail_return_screen)
        )
        self.date_group_detail_screen.exclusion_changed.connect(self._on_group_detail_exclusion_changed)

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

    def _start_scan(self, paths: list, resize: bool = True):
        self._current_scan_paths = paths
        self._scan_origin_paths = paths
        self._resume_base_result = None
        self._resume_base_planned_total = 0
        if resize:
            self.resize(*self._SCANNING_SIZE)
        self.stack.setCurrentWidget(self.scanning_screen)
        self.scanning_screen.start_scan(paths)

    def _ensure_scanned_then(self, then_fn):
        """정리 허브의 중복/유사/날짜별/도시별 카드 공통 진입점(2026-09-10,
        사용자 요청 — "정리" 카드를 누르면 스캔 없이 바로 허브부터 보여주고,
        카드를 실제로 골라야 그때 전체 스캔을 시작한다). 이미 스캔이 끝나
        있으면(같은 세션에서 다른 카드를 먼저 눌렀던 경우) 재스캔 없이 바로
        then_fn()을 실행한다 — 넷 다 같은 ScanResult(해시·EXIF 전부)를
        공유하므로 두 번째부터는 카드를 바꿔도 다시 스캔하지 않는다."""
        if self.result_screen.result is not None:
            then_fn()
            return
        self._pending_organize_destination = then_fn
        # 허브가 이미 보통 크기로 떠 있으므로(land_on_organize) 창 크기는
        # 건드리지 않는다 — resize=False.
        self._start_scan(self._organize_paths, resize=False)

    def _start_light_cat_finder_scan(self, paths: list[str]):
        """"정리 > 고양이 찾기" 빠른 경로 — core/scanner.py의 무거운 진단
        스캔(core/analyzer.py::analyze_file, 파일마다 SHA-256 전체 해시 +
        이미지 디코딩)을 건너뛰고 파일 목록만 가볍게 모은 뒤 곧장 고양이
        찾기로 간다. 정리 허브가 이미 보통 크기로 떠 있는 상태에서 카드를
        눌러 시작하므로(2026-09-10) 창 크기는 건드리지 않는다 — 상단 주석의
        "결과 화면 이후로는 창 크기를 다시 건드리지 않는다" 원칙."""
        self._light_scan_worker = _LightListWorker(paths, self)
        self._light_scan_worker.finished_listing.connect(self._on_light_scan_finished)
        self.light_scan_progress_dialog.start("사진 목록을 모으는 중")
        # 총 개수를 미리 알 수 없어(진단처럼 파일마다 처리하는 게 아니라 폴더
        # 순회 자체) 퍼센트 대신 바쁨(busy) 표시로 보여준다.
        self.light_scan_progress_dialog.bar.setRange(0, 0)
        self.light_scan_progress_dialog.status_label.setText("폴더를 훑어보는 중...")
        self._light_scan_worker.start()
        self.light_scan_progress_dialog.exec()

    def _on_light_scan_cancel_requested(self):
        if self._light_scan_worker is not None:
            self._light_scan_worker.cancel()

    def _on_light_scan_finished(self, result):
        self.light_scan_progress_dialog.accept()
        self.light_scan_progress_dialog.bar.setRange(0, 100)  # organize_progress_dialog와 인스턴스가 달라 공유 걱정은 없지만, 다음 실행을 위해 원상복구
        worker = self._light_scan_worker
        self._light_scan_worker = None
        if worker is not None:
            worker.wait()

        if result.total == 0:
            _info_dialog(self, "이미지 파일이 없습니다.")
            self.stack.setCurrentWidget(self.organize_hub_screen)
            return

        self.cat_finder_screen.set_output_root(str(self._default_organize_output_dir() / "고양이_사진"))
        self.cat_finder_screen.set_result(result)
        self.stack.setCurrentWidget(self.cat_finder_screen)

    def _default_organize_output_dir(self) -> Path:
        """gui/date_organize_screen.py::_open_date_organize·_open_city_organize와
        같은 기준(원래 선택한 경로가 폴더면 그 폴더, 파일이면 그 파일의
        부모 폴더) — "정리 방식" 저장 위치 기본값."""
        origin = Path(self._scan_origin_paths[0]) if self._scan_origin_paths else Path.cwd()
        return origin if origin.is_dir() else origin.parent

    def _on_resume_requested(self):
        """검사 결과 화면의 '이어서 검사' 버튼 — 나머지 파일만 마저 스캔한다."""
        if self._pending_remaining_paths is None or self.result_screen.result is None:
            return
        self._resume_base_result = self.result_screen.result
        self._resume_base_planned_total = self._pending_planned_total
        self._current_scan_paths = self._pending_remaining_paths
        self.resize(*self._SCANNING_SIZE)
        self.stack.setCurrentWidget(self.scanning_screen)
        self.scanning_screen.start_scan(self._current_scan_paths)

    def _on_scan_finished(self, result, cancelled: bool, planned_total: int, remaining_paths: list):
        if self._resume_base_result is not None:
            result = self._resume_base_result.merge(result)
            planned_total = self._resume_base_planned_total or planned_total
            self._resume_base_result = None
            self._resume_base_planned_total = 0

        pending_destination = self._pending_organize_destination
        self._pending_organize_destination = None
        # "정리" 카드에서 시작된 세션인지 — 이 스캔이 _ensure_scanned_then으로
        # 미뤄졌다 지금 막 끝난 것이거나(pending_destination), 아직 카드를
        # 하나도 안 눌러 pending_destination이 없어도 self._organize_paths가
        # 있으면 정리 허브가 이 세션의 "홈"이라는 뜻이다.
        from_organize_hub = pending_destination is not None or self._organize_paths is not None

        if result.total == 0:
            if not cancelled:
                _info_dialog(self, "이미지 파일이 없습니다.")
            if from_organize_hub:
                # 정리 허브는(이미 보통 크기로 떠 있고 카드도 여전히 유효하니)
                # 세션을 닫는 대신 그리로 돌아간다.
                self.stack.setCurrentWidget(self.organize_hub_screen)
            else:
                self.close()
            return

        # '이어서 검사' 버튼이 다음에 눌렸을 때 쓸 수 있도록 현재 상태를 기억해둔다
        self._pending_remaining_paths = remaining_paths if cancelled else None
        self._pending_planned_total = planned_total
        self.result_screen.set_result(
            result,
            cancelled=cancelled,
            planned_total=planned_total,
            remaining_paths=remaining_paths,
            scan_paths=self._scan_origin_paths,
        )

        if pending_destination is not None:
            # 정리 허브의 카드(중복/유사/날짜별/도시별)를 눌러 미뤄뒀던 스캔이
            # 방금 끝났다 — 허브의 "사진 목록"(뷰어 영역)을 채우고 고른
            # 화면으로 들어간다. 허브는 이미 보통 크기로 떠 있어서 창 크기는
            # 안 건드린다.
            self.organize_hub_screen.set_result(result)
            pending_destination()
        elif from_organize_hub:
            self.organize_hub_screen.set_result(result)
            self.stack.setCurrentWidget(self.organize_hub_screen)
        else:
            # 중복 화면은 그룹이 수백 개면 카드를 그만큼 만들어야 해서 스캔 하나
            # 끝날 때마다 미리 만들어두면(당장 보지도 않는데) 그때마다 응답 없음이
            # 뜬다 — 사용자가 "중복 파일 보기"를 실제로 눌렀을 때만 만든다.
            self.resize(*self._NORMAL_SIZE)
            self.setMinimumSize(*self._MIN_NORMAL_SIZE)
            self.stack.setCurrentWidget(self.result_screen)

    def _open_detail(self, info, group=None, return_to=None):
        self._detail_return_screen = return_to or self.result_screen
        # 중복/유사 사진 화면에서는 "이게 정말 맞나" 확인하러 들어온 것이라
        # 복구/변환/화질 개선 같은 편집 액션은 감춘다(gui/detail_screen.py::
        # set_review_only 참고) — gui/date_group_detail_screen.py와 같은 원칙.
        self.detail_screen.set_review_only(
            return_to in (self.duplicate_screen, self.similar_screen, self.cat_finder_screen)
        )
        # group을 주면(중복/유사 화면의 표에서 열었을 때) 상세 화면에서
        # 방향키로 같은 그룹의 다음/이전 사진을 넘나들 수 있다(2026-09-08,
        # 사용자 요청).
        self.detail_screen.set_file(info, group=group)
        self.stack.setCurrentWidget(self.detail_screen)

    def _open_recovery(self, files, mode):
        self.recovery_screen.set_files(files, preselected_mode=mode)
        self.stack.setCurrentWidget(self.recovery_screen)

    def _back_from_organize_hub(self):
        self.stack.setCurrentWidget(self.result_screen)

    def _refresh_after_organize_action(self):
        """중복/유사 정리, 휴지통 복원 등으로 검사 결과가 바뀐 뒤 정리 허브로
        돌아갈 때 표/칩(검사 결과 화면)과 카드 배지(정리 허브)를 같이
        새로고침한다 — 둘 중 하나만 갱신하면 반대쪽에 옛 개수가 남는다."""
        self.result_screen.refresh_current_result()
        self.organize_hub_screen.set_result(self.result_screen.result)

    def _back_from_duplicates(self):
        # duplicate_screen이 "정리 실행"으로 이미 self.result_screen.result(같은
        # ScanResult 객체)에서 파일을 뺐어도(ScanResult.remove), 검사 결과 화면의
        # 표/칩은 따로 다시 그려주지 않으면 그대로 갱신 안 된 채 남는다 — 휴지통에
        # 옮긴 사진이 검사 결과 목록에 계속 보이던 문제.
        self._refresh_after_organize_action()
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _back_from_similar(self):
        self._refresh_after_organize_action()
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_duplicates(self):
        # 2026-09-10: 아직 스캔 전이면(정리 허브를 방금 열었을 때) 여기서
        # 전체 스캔부터 시작하고, 끝나면 아래 로직을 다시 실행한다
        # (_ensure_scanned_then 참고). 이미 스캔돼 있으면(다른 카드를 먼저
        # 눌렀던 경우 등) 바로 실행된다.
        def proceed():
            result = self.result_screen.result
            if not result or not result.duplicate_groups():
                # 처리할 중복이 아예 없으면 빈 화면을 보여줄 필요 없이 정리
                # 허브로 바로 돌아간다.
                _info_dialog(self, "중복된 파일이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            self.duplicate_screen.set_result(result)
            self.stack.setCurrentWidget(self.duplicate_screen)

        self._ensure_scanned_then(proceed)

    def _open_similar(self):
        def proceed():
            result = self.result_screen.result
            if not result or not result.files:
                _info_dialog(self, "정리할 사진이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            # similar_groups() 계산 자체가 느릴 수 있어(퍼셉추얼 해시 쌍 비교)
            # 여기서 미리 확인하지 않고, SimilarScreen이 백그라운드로 계산하는
            # 동안 진행률 팝업을 보여준다 — 결과가 없으면 화면 자체가 빈
            # 상태를 보여준다.
            self.similar_screen.set_result(result)
            self.stack.setCurrentWidget(self.similar_screen)

        self._ensure_scanned_then(proceed)

    def _open_date_organize(self):
        def proceed():
            result = self.result_screen.result
            if not result or not result.files:
                _info_dialog(self, "정리할 사진이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            self.date_organize_screen.set_result(result)
            self.date_organize_screen.set_output_root(str(self._default_organize_output_dir() / "날짜별_정리"))
            self.stack.setCurrentWidget(self.date_organize_screen)

        self._ensure_scanned_then(proceed)

    def _back_from_date_organize(self):
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_date_group_detail(self, label: str, files: list):
        self._group_detail_return_screen = self.date_organize_screen
        excluded = self.date_organize_screen.group_excluded(label)
        self.date_group_detail_screen.set_group(label, files, excluded_paths=excluded)
        self.stack.setCurrentWidget(self.date_group_detail_screen)

    def _open_city_organize(self):
        def proceed():
            result = self.result_screen.result
            if not result or not result.files:
                _info_dialog(self, "정리할 사진이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            self.city_organize_screen.set_result(result)
            self.city_organize_screen.set_output_root(str(self._default_organize_output_dir() / "도시별_정리"))
            self.stack.setCurrentWidget(self.city_organize_screen)

        self._ensure_scanned_then(proceed)

    def _back_from_city_organize(self):
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_cat_finder(self):
        # 고양이 찾기는 중복/유사/날짜별/도시별의 전체 스캔과 무관하다 — 이미
        # 그 스캔이 끝나 있으면(다른 카드를 먼저 눌렀던 경우) 재스캔 없이
        # 그 결과를 그대로 쓰고, 아직 스캔 전이면 자기만의 가벼운 경로
        # (_start_light_cat_finder_scan, 손상 검사·해시 생략)로 곧장 간다.
        result = self.result_screen.result
        if result is not None and result.files:
            self.cat_finder_screen.set_output_root(str(self._default_organize_output_dir() / "고양이_사진"))
            self.cat_finder_screen.set_result(result)
            self.stack.setCurrentWidget(self.cat_finder_screen)
            return
        self._start_light_cat_finder_scan(self._organize_paths)

    def _back_from_cat_finder(self):
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_city_group_detail(self, label: str, info, files: list):
        self._group_detail_return_screen = self.city_organize_screen
        excluded = self.city_organize_screen.group_excluded(label)
        self.date_group_detail_screen.set_group(label, files, excluded_paths=excluded, initial_file=info)
        self.stack.setCurrentWidget(self.date_group_detail_screen)

    def _on_group_detail_exclusion_changed(self, label: str, excluded: set):
        # _group_detail_return_screen은 항상 date_organize_screen 또는
        # city_organize_screen 중 하나이고, 둘 다 같은 시그니처의
        # set_group_excluded(label, excluded_paths)를 갖고 있다.
        self._group_detail_return_screen.set_group_excluded(label, excluded)

    def _confirm_move_if_needed(self, mode: str) -> bool:
        if mode != "move":
            return True
        return _confirm_dialog(
            self,
            "이동을 선택하셨어요.<br><br>"
            "원본 파일이 새 폴더로 옮겨지고 원래 위치에는 남지 않아요.<br>"
            "계속할까요?",
            confirm_text="이동 시작",
            cancel_text="취소",
        )

    def _start_organize_worker(self, run_fn, mode: str, output_root: str):
        self._organize_worker = _OrganizeWorker(run_fn, mode, output_root, self)
        self._organize_worker.progress.connect(self._on_organize_progress)
        self._organize_worker.finished_batch.connect(self._on_organize_finished)

        title = "이동하는 중" if mode == "move" else "복사하는 중"
        self.organize_progress_dialog.start(title)
        self._organize_worker.start()
        self.organize_progress_dialog.exec()

    def _on_date_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        groups = self.date_organize_screen.groups()
        output_root = self.date_organize_screen.output_root()
        granularity = self.date_organize_screen.granularity()
        run_fn = lambda progress_callback, should_cancel: organize_by_date(
            groups, mode, output_root, granularity=granularity,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_city_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        groups = self.city_organize_screen.groups()
        output_root = self.city_organize_screen.output_root()
        run_fn = lambda progress_callback, should_cancel: organize_by_city(
            groups, mode, output_root,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_cat_finder_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        files = self.cat_finder_screen.matched_files()
        output_root = self.cat_finder_screen.output_root()
        run_fn = lambda progress_callback, should_cancel: organize_cat_finder_results(
            files, mode, output_root,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        # 2026-09-10부터 organize_hub_screen은 어느 경로로 오든(가벼운 고양이
        # 찾기든, 다른 카드로 이미 스캔했든) 항상 채워져 있으므로 완료 후
        # 기본값(그리로 돌아감)을 그대로 쓴다.
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_organize_progress(self, current: int, total: int, filename: str):
        self.organize_progress_dialog.update_progress(current, total, filename)

    def _on_organize_cancel_requested(self):
        if self._organize_worker is not None:
            self._organize_worker.cancel()

    def _on_organize_finished(self, outcomes):
        self.organize_progress_dialog.accept()
        worker = self._organize_worker
        self._organize_worker = None
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
            self._refresh_after_organize_action()

        output_root = worker.output_root if worker is not None else ""

        lines = [f"{len(newly_done)}개 정리했습니다."]
        if skipped:
            lines.append(f"{len(skipped)}개는 이미 있어서 건너뛰었습니다.")
        if failed:
            lines.append(f"{len(failed)}개는 실패했습니다:")
            lines.extend(f"{o.original.filename} ({o.error_message})" for o in failed[:5])

        _info_dialog_with_folder(self, "\n".join(lines), output_root)

        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_trash(self, return_to=None, moved_infos: list | None = None):
        self._trash_return_screen = return_to or self.result_screen
        if moved_infos:
            # 임시휴지통이 이제 "옮긴 파일이 있던 폴더마다" 따로 생기므로
            # (utils/trash.py), 이번에 실제로 옮겨진 파일들이 어느 폴더에서
            # 왔는지로 보여줄 임시휴지통 목록을 계산한다.
            trash_dirs = sorted({trash.trash_dir_for(info.path) for info in moved_infos})
            self.trash_screen.set_trash_dirs(trash_dirs)
        self.trash_screen.refresh()
        self.stack.setCurrentWidget(self.trash_screen)

    def _back_from_trash(self):
        if self._trash_return_screen is self.similar_screen and self.similar_screen.has_pending():
            self.stack.setCurrentWidget(self.similar_screen)
        elif self.duplicate_screen.has_pending():
            self.stack.setCurrentWidget(self.duplicate_screen)
        else:
            # 더 처리할 그룹이 없어 정리 허브로 바로 돌아가는 경우 — 그동안
            # 중복/유사 정리로 빠진 파일들이 표/칩/카드 배지에 반영되게 새로고침한다.
            self._refresh_after_organize_action()
            self.stack.setCurrentWidget(self.organize_hub_screen)

    def _on_recovery_finished(self, outcomes, output_dir):
        if self.result_screen.result is not None:
            for outcome in outcomes:
                # 원래 '정상'이던 파일은 복구가 아니라 단순 변환이므로 상태를 바꾸지 않는다
                if outcome.success and outcome.original.status != FileStatus.NORMAL:
                    self.result_screen.result.mark_recovered(outcome.original)
            self.result_screen.refresh_current_result()

        self.recovery_result_screen.set_outcomes(outcomes, output_dir)
        self.stack.setCurrentWidget(self.recovery_result_screen)

    # --- 창 종료 ---------------------------------------------------------

    def closeEvent(self, event):
        # 검사/복구/날짜별 정리처럼 "취소하면 안 되는" 진행 중 작업은 실제로
        # 끝날 때까지 창을 못 닫게 막는다 — 스레드가 도는 중에 창(과 워커)이
        # 같이 없어지면 ("QThread: Destroyed while thread is still running")
        # 죽기도 하고, 파일 이동 같은 작업을 중간에 끊으면 상태가 애매해진다.
        scan_worker = getattr(self.scanning_screen, "worker", None)
        recovery_worker = getattr(self.recovery_screen, "worker", None)
        if (
            (scan_worker is not None and scan_worker.isRunning())
            or (recovery_worker is not None and recovery_worker.isRunning())
            or (self._organize_worker is not None and self._organize_worker.isRunning())
            or (self._light_scan_worker is not None and self._light_scan_worker.isRunning())
        ):
            event.ignore()
            return

        # 썸네일 미리보기 로딩은(휴지통/날짜 그룹 상세) 다시 만들면 그만인
        # 순수 화면용 데이터라 막을 필요는 없고, 그냥 안전하게 멈추기만 한다
        # (gui/trash_screen.py::stop_pending_work 참고) — 이걸 안 하면 이
        # 창을 닫는 순간 백그라운드 로딩이 아직 돌고 있을 때 같은 크래시
        # 위험이 있다.
        self.trash_screen.stop_pending_work()
        self.date_group_detail_screen.stop_pending_work()

        self.closed.emit(self)
        super().closeEvent(event)
