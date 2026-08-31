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
from gui.scan_session_window import ScanSessionWindow


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

    def _start_session(self, paths: list):
        session = ScanSessionWindow(self.home_screen, paths, parent=self)
        session.closed.connect(self._on_session_closed)
        self._sessions.append(session)
        session.show()

    def _on_session_closed(self, session: ScanSessionWindow):
        if session in self._sessions:
            self._sessions.remove(session)
