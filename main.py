"""
main.py — PicMedic 실행 진입점

실행:
    python main.py
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def _asset_path(name: str) -> str:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # PyInstaller가 풀어놓은 임시 경로
    else:
        base = Path(__file__).resolve().parent
    return str(base / "assets" / name)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PicMedic")
    app.setWindowIcon(QIcon(_asset_path("icon.ico")))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
