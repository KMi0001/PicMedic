"""
gui/scan_session_window.py

스캔 1회를 처음부터 끝까지 담당하는 독립 창.
검사 진행 -> 검사 결과 -> (상세) -> 복구 -> 복구 결과 -> 결과로 복귀, 를 이 창 하나 안에서
QStackedWidget으로 전환한다 (예전엔 gui/main_window.py가 이 전체를 앱 전체 싱글턴
화면들로 관리했음). gui/main_window.py는 파일/폴더를 선택할 때마다 이 창을 새로
띄우기만 해서, 여러 폴더를 동시에 검사할 수 있다 (PRD_MVP우선순위.md 갭 #10).

화면이 14개, 전환/워커 콜백 메서드가 50개를 넘어서면서(2026-09-11 리뷰) 이 파일
하나에 다 두면 기능 하나 찾기가 점점 어려워졌다. 그래서 기능별 전환 로직을
믹스인 클래스로 나눠 별도 파일로 뺐다 — 아래 클래스들은 전부 self.xxx로
ScanSessionWindow.__init__이 준비한 같은 속성(stack, result_screen, ...)에
접근하는 다중 상속 믹스인이라, 시그널 배선(_wire_signals)과 런타임 동작은
분리 전과 동일하다. 이 클래스 본체(ScanSessionWindow)에는 여러 화면이 공유하는
뼈대(창 생성, 화면 목록, 시그널 배선, 스캔 시작/이어서 검사, 창 닫기)만 남긴다:
- gui/scan_session_workers.py — 백그라운드 워커(QThread)와 보조 위젯
- gui/scan_session_organize_mixin.py — 날짜별/도시별/고양이 찾기 "정리하기" 실행 공통 로직
- gui/scan_session_duplicates_mixin.py — 중복/유사 사진 카드
- gui/scan_session_date_city_mixin.py — 날짜별/도시별 정리 카드 + 그룹 상세
- gui/scan_session_cat_finder_mixin.py — 고양이 찾기 카드
- gui/scan_session_detail_mixin.py — 상세보기/복구/임시휴지통
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from gui.common_dialogs import info_dialog as _info_dialog, ProgressDialog
from gui.scanning_screen import ScanningScreen
from gui.result_screen import ResultScreen
from gui.theme import COLORS, get_stylesheet
from utils.native_titlebar import apply_titlebar_theme
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
from gui.scan_session_workers import _OrganizeWorker, _LightListWorker, _CurrentOnlyStack
from gui.scan_session_organize_mixin import OrganizeExecutionMixin
from gui.scan_session_duplicates_mixin import DuplicatesSimilarMixin
from gui.scan_session_date_city_mixin import DateCityOrganizeMixin
from gui.scan_session_cat_finder_mixin import CatFinderMixin
from gui.scan_session_detail_mixin import DetailRecoveryTrashMixin

__all__ = ["ScanSessionWindow"]


class ScanSessionWindow(
    QWidget,
    OrganizeExecutionMixin,
    DuplicatesSimilarMixin,
    DateCityOrganizeMixin,
    CatFinderMixin,
    DetailRecoveryTrashMixin,
):
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
        self.setStyleSheet(get_stylesheet())
        apply_titlebar_theme(self, COLORS["bg"], COLORS["text"])
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
        self.scanning_screen.scan_failed.connect(self._on_scan_failed)

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

    def _on_scan_failed(self, message: str):
        """검사가 예상 못한 오류로 끝난 경우(gui/scanning_screen.py::ScanWorker.run
        참고). 진행 화면에 그대로 두면 사용자가 빠져나갈 방법이 없으므로,
        안내하고 들어온 곳(정리 허브 또는 창 닫기)으로 돌려보낸다."""
        from_organize_hub = self._pending_organize_destination is not None or self._organize_paths is not None
        self._pending_organize_destination = None
        self._resume_base_result = None
        self._resume_base_planned_total = 0

        # 워커 스레드가 완전히 끝나기 전에 close()를 부르면 아래 closeEvent가
        # isRunning()을 보고 닫기를 막아버려서, 오히려 멈춘 검사 화면에 갇힌다.
        worker = getattr(self.scanning_screen, "worker", None)
        if worker is not None:
            worker.wait()

        _info_dialog(self, f"검사 중 예상하지 못한 오류가 발생했습니다.\n\n{message}")
        if from_organize_hub:
            self.stack.setCurrentWidget(self.organize_hub_screen)
        else:
            self.close()

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
