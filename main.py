import os
import sys

from pillow_heif import register_heif_opener
register_heif_opener()
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QLabel,
    QFileDialog, QMessageBox, QVBoxLayout, QWidget
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Slot

from PIL import Image


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PicMedic")
        self.resize(400, 500)

        self.image_path = None

        # ---------------- UI ----------------
        self.upload_btn = QPushButton("이미지 업로드")
        self.scan_btn = QPushButton("검사 (Scan)")
        self.restore_btn = QPushButton("초기화 (Restore)")

        self.image_label = QLabel("이미지 없음")
        self.score_label = QLabel("")
        self.result_label = QLabel("")

        self.image_label.setScaledContents(True)

        layout = QVBoxLayout()
        layout.addWidget(self.upload_btn)
        layout.addWidget(self.scan_btn)
        layout.addWidget(self.restore_btn)
        layout.addWidget(self.image_label)
        layout.addWidget(self.score_label)
        layout.addWidget(self.result_label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # ---------------- SIGNAL ----------------
        self.upload_btn.clicked.connect(self.load_image)
        self.scan_btn.clicked.connect(self.run_scan)
        self.restore_btn.clicked.connect(self.restore_image)

    # ---------------- IMAGE LOAD ----------------
    @Slot()
    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 선택",
            "",
            "Images (*.png *.jpg *.jpeg *.heic)"
        )

        if not file_path:
            return

        # HEIC 변환 처리
        if file_path.lower().endswith(".heic"):
            file_path = self.convert_heic_to_jpg(file_path)

        self.image_path = file_path

        pixmap = QPixmap(file_path)
        self.image_label.setPixmap(pixmap)

        self.result_label.setText("이미지 로드 완료")

    # ---------------- HEIC CONVERT ----------------

    def convert_heic_to_jpg(self, path):
        try:
            img = Image.open(path)

            new_path = os.path.splitext(path)[0] + ".jpg"
            img.convert("RGB").save(new_path, "JPEG")

            return new_path

        except Exception as e:
            QMessageBox.critical(self, "변환 실패", str(e))
            return path
    # ---------------- SCAN ----------------
    @Slot()
    def run_scan(self):
        if not self.image_path:
            QMessageBox.warning(self, "오류", "이미지를 먼저 업로드하세요.")
            return

        result = self.analyze_image(self.image_path)
        self.update_ui(result)

    # ---------------- ANALYZE (더미) ----------------
    def analyze_image(self, path):
        # 여기 나중에 cv2 / AI 붙이면 됨
        return {
            "score": 85,
            "status": "OK",
            "message": "분석 완료 (테스트)"
        }

    # ---------------- UI UPDATE ----------------
    def update_ui(self, result):
        self.score_label.setText(f"Score: {result['score']}")
        self.result_label.setText(f"{result['status']} - {result['message']}")

    # ---------------- RESTORE ----------------
    @Slot()
    def restore_image(self):
        self.image_path = None

        self.image_label.clear()
        self.image_label.setText("이미지 없음")

        self.score_label.setText("")
        self.result_label.setText("초기화 완료")


# ---------------- RUN ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())