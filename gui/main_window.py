"""
gui/main_window.py

메인 창은 홈 화면만 상주시킨다. 파일/폴더를 선택할 때마다 검사~복구 전체 흐름을
담당하는 독립 창(gui/scan_session_window.py::ScanSessionWindow)을 새로 띄워서,
여러 폴더를 동시에 검사할 수 있게 한다 (PRD_MVP우선순위.md 갭 #10).
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from gui.theme import APP_STYLESHEET
from gui.home_screen import HomeScreen
from gui.scan_session_window import ScanSessionWindow, _info_dialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PicMedic — 사진 진단 · 복구 · 정리")
        self.resize(760, 600)
        self.setStyleSheet(APP_STYLESHEET)

        self.home_screen = HomeScreen()
        self.setCentralWidget(self.home_screen)

        # 세션 창은 파이썬 참조가 하나도 안 남으면 워커가 도는 중에도 GC될 수 있어서
        # (「QThread: Destroyed while thread is still running」) 살아있는 동안 붙잡아둔다.
        self._sessions: list[ScanSessionWindow] = []

        self.home_screen.paths_chosen.connect(self._start_session)
        self.home_screen.organize_requested.connect(self._start_organize_session)

    def _start_organize_session(self, paths: list):
        self._start_session(paths, land_on_organize=True)

    def _start_session(self, paths: list, land_on_organize: bool = False):
        # parent를 안 주는 이유: Qt.Window 플래그를 가진 위젯이 부모까지 있으면
        # Windows에서 최대화는 되는데 테두리 드래그 리사이즈가 안 먹는 문제가
        # 있었다(2026-09-08, 사용자 리포트) — 그래서 완전히 독립된 창으로 띄우고
        # 스타일시트는 ScanSessionWindow가 직접 적용한다(gui/scan_session_window.py
        # 참고). 그 대신 Qt가 자동으로 자식 창을 닫아주지 않으므로, 아래
        # closeEvent()에서 열려있는 세션 창들을 직접 닫아준다.
        session = ScanSessionWindow(paths, parent=None, land_on_organize=land_on_organize)
        session.closed.connect(self._on_session_closed)
        self._sessions.append(session)
        session.show()

    def _on_session_closed(self, session: ScanSessionWindow):
        if session in self._sessions:
            self._sessions.remove(session)

    def closeEvent(self, event):
        # 세션 창(gui/scan_session_window.py)은 워커가 도는 중엔 자기 창을 못 닫게
        # 막지만, 홈 화면(여기)까지 닫혀버리면 그 세션으로 다시 돌아올 방법이
        # 없어진다 — 검사/복구가 하나라도 진행 중이면 안내하고 막는다.
        if self._has_active_work():
            _info_dialog(
                self,
                "진행 중인 검사/복구가 있어 지금은 홈 화면을 닫을 수 없어요.\n"
                "완료되거나 중단한 뒤 다시 시도해주세요.",
            )
            event.ignore()
            return
        # 세션 창이 이제 Qt 부모가 없는 독립 창이라(위 _start_session 참고) 여기서
        # 닫아주지 않으면 홈 화면을 닫아도 열려있던 세션 창들이 그대로 남는다.
        for session in list(self._sessions):
            session.close()
        super().closeEvent(event)

    def _has_active_work(self) -> bool:
        for session in self._sessions:
            scan_worker = getattr(session.scanning_screen, "worker", None)
            recovery_worker = getattr(session.recovery_screen, "worker", None)
            light_scan_worker = session._light_scan_worker
            if (
                (scan_worker is not None and scan_worker.isRunning())
                or (recovery_worker is not None and recovery_worker.isRunning())
                or (light_scan_worker is not None and light_scan_worker.isRunning())
            ):
                return True
        return False
