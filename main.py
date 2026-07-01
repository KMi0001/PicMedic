import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import STYLE

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)

window = MainWindow()
window.show()

sys.exit(app.exec())