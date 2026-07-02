from PySide6.QtWidgets import QMainWindow, QPushButton, QLabel, QFileDialog, QMessageBox, QWidget, QVBoxLayout
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PicMedic")
        self.resize(500, 600)

        self.image_path = None

        # ----------------------------
        # 1. UI 생성 (먼저 만들어야 함)
        # ----------------------------
        self.upload_btn = QPushButton("이미지 업로드")
        self.scan_btn = QPushButton("검사 (Scan)")
        self.restore_btn = QPushButton("초기화 (Restore)")

        self.image_label = QLabel("이미지 없음")
        self.image_label.setFixedSize(300, 300)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid gray;")

        self.score_label = QLabel("")
        self.result_label = QLabel("")

        # ----------------------------
        # 2. 버튼 연결 (그 다음)
        # ----------------------------
        self.upload_btn.clicked.connect(self.load_image)
        self.scan_btn.clicked.connect(self.run_scan)
        self.restore_btn.clicked.connect(self.restore_image)

        # ----------------------------
        # 3. 레이아웃 구성
        # ----------------------------
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

    # ----------------------------
    # 이미지 업로드
    # ----------------------------
    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 선택",
            "",
            "Images (*.png *.jpg *.jpeg *.heic)"
        )

        if not file_path:
            return

        self.image_path = file_path

        pixmap = QPixmap(file_path)
        pixmap = pixmap.scaled(
            self.image_label.width(),
            self.image_label.height(),
            Qt.KeepAspectRatio
        )

        self.image_label.setPixmap(pixmap)
        self.result_label.setText("이미지 로드 완료")

    # ----------------------------
    # scan 실행
    # ----------------------------
    def run_scan(self):
        if not self.image_path:
            QMessageBox.warning(self, "오류", "이미지를 먼저 업로드하세요.")
            return

        result = self.analyze_image(self.image_path)
        self.update_ui(result)

    # ----------------------------
    # 더미 분석 함수
    # ----------------------------
    def analyze_image(self, path):
        return {
            "score": 85,
            "status": "OK",
            "message": "분석 완료"
        }

    # ----------------------------
    # UI 업데이트
    # ----------------------------
    def update_ui(self, result):
        self.score_label.setText(f"Score: {result['score']}")
        self.result_label.setText(f"{result['status']} - {result['message']}")

    # ----------------------------
    # 초기화
    # ----------------------------
    def restore_image(self):
        self.image_path = None
        self.image_label.clear()
        self.image_label.setText("이미지 없음")
        self.score_label.setText("")
        self.result_label.setText("")