"""
main.py — PicMedic 실행 진입점

실행:
    python main.py
"""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.assets import asset_path


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PicMedic")
    app.setWindowIcon(QIcon(asset_path("icon.ico")))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
