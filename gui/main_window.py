from pathlib import Path

from PySide6.QtWidgets import *
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.current_image = None

        self.setWindowTitle("PicMedic")
        self.resize(1100, 720)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        layout.addStretch()

        # -----------------------
        # Logo
        # -----------------------

        logo = QLabel("🩺")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("font-size:60px;")

        title = QLabel("PicMedic")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:28pt;font-weight:bold;")

        subtitle = QLabel("Restore Memories. Naturally.")
        subtitle.setAlignment(Qt.AlignCenter)

        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addSpacing(25)

        # -----------------------
        # Preview Area
        # -----------------------

        self.preview = QLabel()

        self.preview.setAlignment(Qt.AlignCenter)

        self.preview.setMinimumHeight(320)

        self.preview.setObjectName("DropArea")

        self.preview.setText(
            "📷\n\nDrag & Drop your photo\n\nor\n\nClick Open Image"
        )

        layout.addWidget(self.preview)

        layout.addSpacing(20)

        # -----------------------
        # Buttons
        # -----------------------

        buttons = QHBoxLayout()

        self.openBtn = QPushButton("Open Image")
        self.scanBtn = QPushButton("Scan & Restore")

        buttons.addStretch()
        buttons.addWidget(self.openBtn)
        buttons.addWidget(self.scanBtn)
        buttons.addStretch()

        layout.addLayout(buttons)

        layout.addStretch()

        # -----------------------
        # StatusBar
        # -----------------------

        self.statusBar().showMessage("Ready")

        # -----------------------
        # Signal
        # -----------------------

        self.openBtn.clicked.connect(self.open_image)

    # =====================================
    # Open Image
    # =====================================

    def open_image(self):

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )

        if not filename:
            return

        pixmap = QPixmap(filename)

        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Error",
                "이미지를 열 수 없습니다."
            )
            return

        self.current_image = filename

        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )

        self.statusBar().showMessage(
            f"Loaded : {Path(filename).name}"
        )