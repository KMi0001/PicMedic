from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.current_image = None

        self.setWindowTitle("PicMedic v0.2")
        self.resize(1200, 750)

        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # ---------- Logo ----------
        logo = QLabel("🩺")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("font-size:60px;")

        title = QLabel("PicMedic")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:28pt;font-weight:bold;")

        subtitle = QLabel("Restore Memories. Naturally.")
        subtitle.setAlignment(Qt.AlignCenter)

        main_layout.addWidget(logo)
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)
        main_layout.addSpacing(20)

        # ---------- Preview ----------
        preview_layout = QHBoxLayout()

        self.original_preview = self.create_preview("Original")
        self.restored_preview = self.create_preview("Restored")

        preview_layout.addWidget(self.original_preview)
        preview_layout.addWidget(self.restored_preview)

        main_layout.addLayout(preview_layout)

        # ---------- Buttons ----------
        button_layout = QHBoxLayout()

        self.open_btn = QPushButton("Open Image")
        self.scan_btn = QPushButton("Scan & Restore")

        button_layout.addStretch()
        button_layout.addWidget(self.open_btn)
        button_layout.addWidget(self.scan_btn)
        button_layout.addStretch()

        main_layout.addSpacing(15)
        main_layout.addLayout(button_layout)

        self.statusBar().showMessage("Ready")

        self.open_btn.clicked.connect(self.open_image)

    def create_preview(self, title):

        container = QWidget()

        layout = QVBoxLayout(container)

        label = QLabel(title)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-weight:bold;font-size:14px;")

        preview = QLabel()

        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumSize(450, 400)

        preview.setStyleSheet("""
            border:2px dashed #BFC7D5;
            border-radius:12px;
            background:white;
        """)

        preview.setText("No Image")

        layout.addWidget(label)
        layout.addWidget(preview)

        return container

    def open_image(self):

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )

        if not filename:
            return

        self.load_image(filename)

    def load_image(self, filename):

        pixmap = QPixmap(filename)

        if pixmap.isNull():
            QMessageBox.warning(
                self,
                "Error",
                "이미지를 열 수 없습니다."
            )
            return

        self.current_image = filename

        preview = self.original_preview.findChildren(QLabel)[1]

        preview.setPixmap(
            pixmap.scaled(
                preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

        self.statusBar().showMessage(
            f"Loaded : {Path(filename).name}"
        )