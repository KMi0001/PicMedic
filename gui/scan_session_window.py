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
- gui/scan_session_organize_mixin.py — 날짜별/도시별/카테고리 찾기 "정리하기" 실행 공통 로직
- gui/scan_session_duplicates_mixin.py — 중복/유사 사진 카드
- gui/scan_session_date_city_mixin.py — 날짜별/도시별 정리 카드 + 그룹 상세
- gui/scan_session_category_finder_mixin.py — 카테고리 찾기 카드(동물친구들/음식/스크린샷/야경/풍경)
- gui/scan_session_detail_mixin.py — 상세보기/복구/임시휴지통
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from core.category_finder import CATEGORIES as CATEGORY_FINDER_DEFS
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
from gui.city_organize_screen import CityOrganizeScreen
from gui.date_group_detail_screen import DateGroupDetailScreen
from gui.trash_screen import TrashScreen
from gui.category_finder_screen import CategoryFinderScreen
from gui.scan_session_workers import _OrganizeWorker, _CurrentOnlyStack
from gui.scan_session_organize_mixin import OrganizeExecutionMixin
from gui.scan_session_duplicates_mixin import DuplicatesSimilarMixin
from gui.scan_session_date_city_mixin import DateCityOrganizeMixin
from gui.scan_session_category_finder_mixin import CategoryFinderMixin
from gui.scan_session_detail_mixin import DetailRecoveryTrashMixin

__all__ = ["ScanSessionWindow"]


class ScanSessionWindow(
    QWidget,
    OrganizeExecutionMixin,
    DuplicatesSimilarMixin,
    DateCityOrganizeMixin,
    CategoryFinderMixin,
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
        main_window=None,
    ):
        super().__init__(parent)
        # "홈" 버튼(_go_home)이 이 세션 창을 닫은 뒤 홈 화면을 실제로 앞에
        # 띄우는 데 쓴다 — Qt 부모 관계가 아니라 그냥 참조만 들고 있는 것.
        self._main_window = main_window
        # 2026-09-13: gui/home_screen.py의 "검사"와 "정리" 카드를 하나로 합치면서
        # (사용자 요청) 예전에 여기 있던 "정리 카드는 스캔 없이 곧장 허브부터
        # 보여주고, 카드를 실제로 골라야 그때 전체 스캔을 시작한다"는 지연 스캔
        # 분기가 없어졌다 — 이제 파일/폴더를 고르면 항상 바로 전체 스캔부터
        # 시작하고, 끝나면 검사 결과 화면(정리 카드 포함)으로 간다.
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
        self.duplicate_screen = DuplicateScreen()
        self.similar_screen = SimilarScreen()
        self.date_organize_screen = DateOrganizeScreen()
        self.date_group_detail_screen = DateGroupDetailScreen()
        self.city_organize_screen = CityOrganizeScreen()
        # 카테고리 찾기 화면들(동물친구들/음식 사진/스크린샷/야경/풍경) —
        # core/category_finder.py::CATEGORIES를 그대로 순회해서 만든다.
        self.category_finder_screens = {
            category_id: CategoryFinderScreen(category_id) for category_id in CATEGORY_FINDER_DEFS
        }
        self.trash_screen = TrashScreen()
        # 날짜별/도시별 "정리하기" 둘 다 같은 진행률 팝업 + 워커를 공유한다
        # (동시에 하나만 실행되므로 화면별로 따로 둘 필요 없음).
        self.organize_progress_dialog = ProgressDialog(self)
        self.organize_progress_dialog.cancel_requested.connect(self._on_organize_cancel_requested)
        self._organize_worker: _OrganizeWorker | None = None

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
            self.city_organize_screen,
            *self.category_finder_screens.values(),
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
        self.stack.setCurrentWidget(self.scanning_screen)
        self._start_scan(paths)

    def _wire_signals(self):
        # Scanning -> Result / (홈으로)
        self.scanning_screen.scan_finished.connect(self._on_scan_finished)
        self.scanning_screen.scan_failed.connect(self._on_scan_failed)

        # Result -> Detail / Recovery / 홈 / 중복·유사·날짜별·도시별·카테고리 찾기 각 화면
        # (2026-09-13: 예전엔 별도 "정리 허브" 화면이 이 카드들을 냈는데, 검사
        # 결과 화면 하나로 합쳤다.)
        self.result_screen.file_selected.connect(self._open_detail)
        self.result_screen.recovery_requested.connect(lambda files: self._open_recovery(files, None))
        self.result_screen.rescan_requested.connect(self._go_home)
        self.result_screen.resume_requested.connect(self._on_resume_requested)
        self.result_screen.duplicates_requested.connect(self._open_duplicates)
        self.result_screen.similar_requested.connect(self._open_similar)
        self.result_screen.date_organize_requested.connect(self._open_date_organize)
        self.result_screen.city_organize_requested.connect(self._open_city_organize)
        self.result_screen.category_finder_requested.connect(self._open_category_finder)

        # 카테고리 찾기 -> 검사 결과 / 상세보기(사진 미리보기) / "이 방식대로 정리하기"
        # — 화면이 여러 개라 클로저로 어느 화면에서 온 신호인지 붙잡아둔다.
        for screen in self.category_finder_screens.values():
            screen.back_requested.connect(self._back_from_category_finder)
            screen.file_selected.connect(
                lambda info, group, screen=screen: self._open_detail(info, group=group, return_to=screen)
            )
            screen.organize_requested.connect(
                lambda mode, screen=screen: self._on_category_finder_organize_requested(screen, mode)
            )

        # 중복 사진 -> 검사 결과 화면 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.duplicate_screen.back_requested.connect(self._back_from_duplicates)
        self.duplicate_screen.view_trash_requested.connect(
            lambda infos: self._open_trash(self.duplicate_screen, infos)
        )
        self.duplicate_screen.file_selected.connect(
            lambda info, group: self._open_detail(info, group=group, return_to=self.duplicate_screen)
        )

        # 유사 사진 -> 검사 결과 화면 / 임시 휴지통 / 상세보기(사진 미리보기)
        self.similar_screen.back_requested.connect(self._back_from_similar)
        self.similar_screen.view_trash_requested.connect(
            lambda infos: self._open_trash(self.similar_screen, infos)
        )
        self.similar_screen.file_selected.connect(
            lambda info, group: self._open_detail(info, group=group, return_to=self.similar_screen)
        )

        # 날짜별 정리 -> 검사 결과 화면 / 그룹 상세(사진 확인)
        self.date_organize_screen.back_requested.connect(self._back_from_date_organize)
        self.date_organize_screen.organize_requested.connect(self._on_date_organize_requested)
        self.date_organize_screen.group_opened.connect(self._open_date_group_detail)

        # 도시별 정리 -> 검사 결과 화면 / 그룹 상세(사진 확인)
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
        # "홈" 버튼(구 "다시 검사") — 예전엔 "홈 화면은 MainWindow 쪽에 항상 떠
        # 있으므로 이 세션 창만 닫으면 된다"고 가정했는데, 세션 창이 부모 없는
        # 독립 창이라 MainWindow가 다른 창 뒤에 가려져 있으면 닫아도 아무것도
        # 앞으로 안 올라와 "그냥 꺼진 것처럼" 보였다(2026-09-18, 사용자 리포트).
        # 명시적으로 앞으로 가져온 뒤 닫는다.
        if self._main_window is not None:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()
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
        안내하고 창을 닫는다."""
        self._resume_base_result = None
        self._resume_base_planned_total = 0

        # 워커 스레드가 완전히 끝나기 전에 close()를 부르면 아래 closeEvent가
        # isRunning()을 보고 닫기를 막아버려서, 오히려 멈춘 검사 화면에 갇힌다.
        worker = getattr(self.scanning_screen, "worker", None)
        if worker is not None:
            worker.wait()

        _info_dialog(self, f"검사 중 예상하지 못한 오류가 발생했습니다.\n\n{message}")
        self.close()

    def _center_on_screen(self) -> None:
        """검사 결과로 넘어가며 작은 검사 중 창(600x440)을 큰 창(1200x820)
        으로 키울 때, resize()는 왼쪽 위 모서리는 그대로 두고 오른쪽/아래로만
        커지므로 화면 중앙에서 벗어나 보였다(2026-09-18, 사용자 리포트 —
        "검사결과 화면 뜨는 위치가 이상한데"). 커진 뒤 지금 이 창이 떠 있는
        모니터의 사용 가능 영역(작업 표시줄 등 제외) 기준으로 다시 가운데로
        옮긴다."""
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.x() + (available.width() - self.width()) // 2
        y = available.y() + (available.height() - self.height()) // 2
        self.move(x, y)

    def _on_scan_finished(self, result, cancelled: bool, planned_total: int, remaining_paths: list):
        if self._resume_base_result is not None:
            result = self._resume_base_result.merge(result)
            planned_total = self._resume_base_planned_total or planned_total
            self._resume_base_result = None
            self._resume_base_planned_total = 0

        if result.total == 0:
            if not cancelled:
                _info_dialog(self, "이미지 파일이 없습니다.")
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

        # 중복 화면은 그룹이 수백 개면 카드를 그만큼 만들어야 해서 스캔 하나
        # 끝날 때마다 미리 만들어두면(당장 보지도 않는데) 그때마다 응답 없음이
        # 뜬다 — 사용자가 "중복 파일 보기"를 실제로 눌렀을 때만 만든다.
        self.resize(*self._NORMAL_SIZE)
        self._center_on_screen()
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
        ):
            event.ignore()
            return

        # 카테고리 찾기 백그라운드 계산(검사 결과 화면)은 조용히 뒤에서 도는
        # 작업이라 위 작업들과 달리 끝날 때까지 창 닫기를 막지 않는다 — 대신
        # 취소하고 짧게 기다려서 스레드가 도는 중에 창이 없어지는 걸 막는다.
        self.result_screen._stop_category_scan()

        # 썸네일 미리보기 로딩은(휴지통/날짜 그룹 상세) 다시 만들면 그만인
        # 순수 화면용 데이터라 막을 필요는 없고, 그냥 안전하게 멈추기만 한다
        # (gui/trash_screen.py::stop_pending_work 참고) — 이걸 안 하면 이
        # 창을 닫는 순간 백그라운드 로딩이 아직 돌고 있을 때 같은 크래시
        # 위험이 있다.
        self.trash_screen.stop_pending_work()
        self.date_group_detail_screen.stop_pending_work()

        self.closed.emit(self)
        super().closeEvent(event)
