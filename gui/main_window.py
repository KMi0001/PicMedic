from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("🩺 PicMedic v0.1")
        self.resize(700, 250)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("사진 폴더를 선택하세요.")

        browse_button = QPushButton("📂 찾아보기")
        browse_button.clicked.connect(self.select_folder)

        scan_button = QPushButton("🔍 Scan")
        scan_button.setEnabled(False)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.folder_edit)
        top_layout.addWidget(browse_button)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("사진 폴더"))
        layout.addLayout(top_layout)
        layout.addSpacing(20)
        layout.addWidget(scan_button, alignment=Qt.AlignCenter)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.status = QStatusBar()
        self.status.showMessage("Ready")
        self.setStatusBar(self.status)

        self.scan_button = scan_button

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "사진 폴더 선택"
        )

        if folder:
            self.folder_edit.setText(folder)
            self.scan_button.setEnabled(True)
            self.status.showMessage("폴더 선택 완료")