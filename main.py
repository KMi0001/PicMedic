"""
main.py — PicMedic 실행 진입점

실행:
    python main.py
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.assets import asset_path
from utils.single_instance import SingleInstance


def _bring_to_front(window: MainWindow) -> None:
    """이미 실행 중일 때 앱을 또 실행하면 호출된다 — 최소화/숨김 상태여도 복원해서 맨 앞으로."""
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowMinimized)
    window.show()
    window.raise_()
    window.activateWindow()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PicMedic")
    app.setWindowIcon(QIcon(asset_path("icon.ico")))

    # 이미 실행 중이면 그 앱의 창을 앞으로 가져오고 이 프로세스는 조용히 종료한다.
    single_instance = SingleInstance()
    if not single_instance.acquire():
        return

    window = MainWindow()
    single_instance.activated.connect(lambda: _bring_to_front(window))
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
