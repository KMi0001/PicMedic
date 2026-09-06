"""
experiments/restore_prototype/app.py

"흐리거나 오래된 사진"을 진짜 복원할 수 있는지 검증하는 프로토타입.
core/gui/utils/models 등 메인 앱 코드를 전혀 import하지 않는다 — 여기서 뭘
바꿔도 메인 앱 빌드에는 영향이 없다.

같은 입력 사진에 대해 세 가지 방식을 나란히 비교한다:
- Real-ESRGAN x4 (일반 사진용, 이미 assets/에 있는 실행 파일 재사용) — 기존
  "화질 개선" 기능과 동일. experiments/upscale_prototype에서 이미 확인했듯
  "복원"이 아니라 "덜 뭉개지는 확대"에 가깝다.
- 클래식 언샤프 마스크 디블러(OpenCV, 추가 다운로드 없음) — AI 없이 "무료로"
  어디까지 되는지 기준선을 보여주기 위함.
- GFPGAN 얼굴 복원 — 아직 미설치 상태. pip 패키지 + PyTorch + 모델 가중치
  다운로드(총 1~2GB 안팎)가 필요해서 사용자 승인 후에만 설치한다. 설치 전에는
  버튼이 비활성화되고 이유를 안내한다.

원본 보호: 이 프로토타입도 원본 파일은 절대 덮어쓰지 않는다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

PROTOTYPE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROTOTYPE_DIR.parent.parent
REALESRGAN_EXE = PROJECT_ROOT / "assets" / "realesrgan" / "realesrgan-ncnn-vulkan.exe"
DEFAULT_TEST_IMAGE = PROTOTYPE_DIR / "test_images" / "old_blurry_portrait.jpg"

PREVIEW_SIZE = 220
CROP_SIZE = 160  # 원본 기준 크롭 한 변(px) — 방식별 결과 배율이 달라도 공정 비교하기 위해 표시 크기를 맞춘다

try:
    import gfpgan  # noqa: F401

    GFPGAN_AVAILABLE = True
except ImportError:
    GFPGAN_AVAILABLE = False


def _load_as_bgr(path: str) -> np.ndarray:
    """cv2.imread는 Windows에서 비ASCII 경로일 때 조용히 실패하므로 바이트로
    읽어서 imdecode로 우회한다(experiments/upscale_prototype과 동일한 이유)."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"파일을 읽을 수 없습니다: {exc}") from exc
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다(지원하지 않는 형식이거나 손상된 파일).")
    return img


def _bgr_to_pixmap(img: np.ndarray, max_size: int) -> QPixmap:
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(qimage.copy())
    return pixmap.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _center_crop(img: np.ndarray, size: int) -> np.ndarray:
    h, w = img.shape[:2]
    ch, cw = min(size, h), min(size, w)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    return img[y0 : y0 + ch, x0 : x0 + cw]


def _run_realesrgan(src: np.ndarray) -> np.ndarray:
    """기존 "화질 개선" 기능과 같은 실행 파일을 서브프로세스로 돌린다."""
    if not REALESRGAN_EXE.exists():
        raise FileNotFoundError(f"Real-ESRGAN 실행 파일을 찾을 수 없습니다: {REALESRGAN_EXE}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        in_path, out_path = tmp_dir / "in.png", tmp_dir / "out.png"
        ok, buf = cv2.imencode(".png", src)
        if not ok:
            raise ValueError("임시 입력 파일을 만들지 못했습니다.")
        buf.tofile(str(in_path))

        proc = subprocess.run(
            [str(REALESRGAN_EXE), "-i", str(in_path), "-o", str(out_path), "-n", "realesrgan-x4plus", "-s", "4"],
            cwd=str(REALESRGAN_EXE.parent),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Real-ESRGAN 실행 실패: {detail or f'exit code {proc.returncode}'}")
        return _load_as_bgr(str(out_path))


def _run_classic_deblur(src: np.ndarray) -> np.ndarray:
    """언샤프 마스크: 가우시안 블러 버전을 원본에서 빼는 방식으로 경계를
    강조한다. 사라진 디테일을 만들어내는 게 아니라 "있는 경계를 더 뚜렷하게"
    할 뿐이라 블러가 심하면 한계가 뚜렷하다 — AI 없이 어디까지 되는지의
    기준선(baseline) 용도."""
    blurred = cv2.GaussianBlur(src, (0, 0), sigmaX=4.0)
    sharpened = cv2.addWeighted(src, 2.2, blurred, -1.2, 0)
    # 언샤프는 노이즈도 같이 증폭시키므로 약하게 노이즈 제거를 한 번 더 걸어준다
    return cv2.fastNlMeansDenoisingColored(sharpened, None, 5, 5, 7, 21)


def _run_gfpgan(src: np.ndarray) -> np.ndarray:
    if not GFPGAN_AVAILABLE:
        raise RuntimeError(
            "GFPGAN이 설치되어 있지 않습니다. 설치하려면 사용자 승인이 필요합니다 "
            "(PyTorch + 모델 가중치 약 1~2GB 다운로드)."
        )
    from gfpgan import GFPGANer

    weights_path = PROTOTYPE_DIR / "gfpgan_weights" / "GFPGANv1.4.pth"
    restorer = GFPGANer(model_path=str(weights_path), upscale=1, arch="clean", channel_multiplier=2)
    _, _, restored = restorer.enhance(src, has_aligned=False, only_center_face=False, paste_back=True)
    return restored


class MethodOption:
    def __init__(self, key: str, label: str, note: str, runner, enabled: bool = True):
        self.key = key
        self.label = label
        self.note = note
        self.runner = runner
        self.enabled = enabled


METHODS = [
    MethodOption("realesrgan", "Real-ESRGAN x4 (기존 화질개선)", "덜 뭉개지게 확대 — 새 디테일 생성 아님", _run_realesrgan),
    MethodOption("classic", "클래식 언샤프 디블러 (무료)", "경계만 강조 — 심한 블러엔 한계", _run_classic_deblur),
    MethodOption(
        "gfpgan",
        "GFPGAN 얼굴 복원",
        "설치됨" if GFPGAN_AVAILABLE else "미설치 — 다운로드 승인 필요",
        _run_gfpgan,
        enabled=GFPGAN_AVAILABLE,
    ),
]


class _CompareWorker(QThread):
    method_done = Signal(str, object, float)  # key, result(np.ndarray) or None, elapsed
    method_failed = Signal(str, str)
    all_done = Signal()

    def __init__(self, src: np.ndarray, methods: list[MethodOption], parent=None):
        super().__init__(parent)
        self._src = src
        self._methods = methods

    def run(self):
        for method in self._methods:
            if not method.enabled:
                continue
            try:
                start = time.perf_counter()
                result = method.runner(self._src)
                elapsed = time.perf_counter() - start
            except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
                self.method_failed.emit(method.key, str(exc))
                continue
            self.method_done.emit(method.key, result, elapsed)
        self.all_done.emit()


class RestorePrototype(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PicMedic 사진 복원 프로토타입 (실험용)")
        self.resize(1180, 620)

        self._input_path: str | None = None
        self._src_img: np.ndarray | None = None
        self._results: dict[str, np.ndarray] = {}
        self._worker: _CompareWorker | None = None
        self._panels: dict[str, tuple[QFrame, QLabel, QLabel]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("사진 복원 프로토타입 — 세 가지 방식 비교")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        outer.addWidget(title)

        note = QLabel(
            "같은 흐리고 오래된 테스트 사진에 세 방식을 각각 돌려서 결과를 나란히 비교합니다. "
            "원본 파일은 절대 바꾸지 않고, 결과는 화면에서만 확인합니다(저장 없음)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        outer.addWidget(note)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)
        self.open_btn = QPushButton("다른 이미지 열기")
        self.open_btn.clicked.connect(self._on_open_clicked)
        control_row.addWidget(self.open_btn)

        self.run_btn = QPushButton("세 방식 모두 실행해서 비교")
        self.run_btn.clicked.connect(self._on_run_clicked)
        control_row.addWidget(self.run_btn)
        control_row.addStretch(1)
        outer.addLayout(control_row)

        self.status_label = QLabel("준비 중...")
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        outer.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        outer.addWidget(self.progress_bar)

        panel_row = QHBoxLayout()
        panel_row.setSpacing(16)
        panel_row.addWidget(self._make_panel("original", "원본 (열화된 테스트 사진)"), stretch=1)
        for method in METHODS:
            panel_row.addWidget(self._make_panel(method.key, method.label, method.note), stretch=1)
        outer.addLayout(panel_row, stretch=1)

        self._load_image(str(DEFAULT_TEST_IMAGE) if DEFAULT_TEST_IMAGE.exists() else None)

    def _make_panel(self, key: str, title: str, note: str = "") -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        caption = QLabel(title)
        caption.setWordWrap(True)
        caption.setStyleSheet("font-weight: 600;")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)

        image_label = QLabel("-")
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setFixedSize(CROP_SIZE, CROP_SIZE)
        image_label.setStyleSheet("color: #999; border: 1px dashed #ccc;")
        layout.addWidget(image_label, alignment=Qt.AlignCenter)

        status = QLabel(note)
        status.setWordWrap(True)
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(status)

        self._panels[key] = (frame, image_label, status)
        return frame

    def _on_open_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 열기", "", "이미지 파일 (*.jpg *.jpeg *.png *.bmp)"
        )
        if path:
            self._load_image(path)

    def _load_image(self, path: Optional[str]):
        if not path:
            self.status_label.setText(
                "테스트 이미지가 없습니다 — 먼저 `python make_test_image.py`를 실행하거나 이미지를 직접 여세요."
            )
            self.run_btn.setEnabled(False)
            return
        try:
            img = _load_as_bgr(path)
        except Exception as exc:
            QMessageBox.warning(self, "열기 실패", f"이미지를 열지 못했습니다:\n{exc}")
            return

        self._input_path = path
        self._src_img = img
        self._results.clear()
        for key, (_, label, status) in self._panels.items():
            if key != "original":
                label.setPixmap(QPixmap())
                label.setText("-")
                method = next((m for m in METHODS if m.key == key), None)
                status.setText(method.note if method else "")

        crop = _center_crop(img, CROP_SIZE)
        self._panels["original"][1].setPixmap(_bgr_to_pixmap(crop, CROP_SIZE))
        h, w = img.shape[:2]
        self.status_label.setText(f"{Path(path).name} · {w}×{h} — \"세 방식 모두 실행해서 비교\"를 눌러보세요.")
        self.run_btn.setEnabled(True)

    def _on_run_clicked(self):
        if self._src_img is None or self._worker is not None:
            return
        self._set_busy(True, "세 방식을 순서대로 실행 중... (완료되는 대로 하나씩 채워집니다)")
        self._worker = _CompareWorker(self._src_img, METHODS, self)
        self._worker.method_done.connect(self._on_method_done)
        self._worker.method_failed.connect(self._on_method_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_method_done(self, key: str, result: np.ndarray, elapsed: float):
        self._results[key] = result
        _, label, status = self._panels[key]
        crop = _center_crop(result, CROP_SIZE)
        label.setPixmap(_bgr_to_pixmap(crop, CROP_SIZE))
        method = next(m for m in METHODS if m.key == key)
        status.setText(f"{method.note} · {elapsed:.2f}초")

    def _on_method_failed(self, key: str, message: str):
        _, _, status = self._panels[key]
        status.setText(f"실패: {message}")

    def _on_worker_finished(self):
        self._worker = None
        self._set_busy(False, "비교 완료.")

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress_bar.setVisible(busy)
        self.open_btn.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        if message:
            self.status_label.setText(message)


def main():
    app = QApplication(sys.argv)
    window = RestorePrototype()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
