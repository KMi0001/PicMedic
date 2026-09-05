"""
experiments/upscale_prototype/app.py

PicMedic 본체와 완전히 분리된 화질 개선(업스케일) 사용성 검증용 프로토타입.
core/gui/utils/models 등 메인 앱 코드를 전혀 import하지 않는다 — 여기서 뭘 바꿔도
메인 앱 빌드에는 영향이 없다. 두 종류의 업스케일러를 비교해본다:
- OpenCV dnn_superres(FSRCNN/EDSR) — 깨끗한 이미지를 인위적으로 다운샘플한
  데이터로 학습되어, 실제 사진의 블러/노이즈/압축 손상에는 약함.
- Real-ESRGAN(ncnn-vulkan) — 실제 사진 같은 손상(블러+노이즈+JPEG 압축)을
  합성해 학습해서, "진짜 지저분한 사진"에 더 잘 먹힘. GPU(Vulkan)로 돈다.

화질/속도가 쓸 만한지 먼저 확인한 뒤에 메인 앱에 통합할지 결정하기 위한 용도.

실행:
    pip install -r experiments/upscale_prototype/requirements.txt
    python experiments/upscale_prototype/app.py

Real-ESRGAN은 Windows용 실행 파일(realesrgan/realesrgan-ncnn-vulkan.exe)이 이미
받아져 있어야 동작한다(현재 Windows 전용 — 이 프로토타입만의 한계이고, 정식
기능으로 만들 때는 macOS 바이너리도 따로 받아야 함).

원본 보호: 이 프로토타입도 원본 파일은 절대 덮어쓰지 않는다 — 결과는 항상
"다른 이름으로 저장"으로만 새 파일에 쓴다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
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

MODELS_DIR = Path(__file__).resolve().parent / "models"
REALESRGAN_DIR = Path(__file__).resolve().parent / "realesrgan"
REALESRGAN_EXE = REALESRGAN_DIR / "realesrgan-ncnn-vulkan.exe"

PREVIEW_SIZE = 300
CROP_PREVIEW_SIZE = 260
CROP_SIZE = 128  # 원본 기준 크롭 한 변 길이(px) — 두 방식의 확대 결과를 공정하게 비교하기 위함

_HEIC_EXTENSIONS = (".heic", ".heif")


@dataclass
class ModelOption:
    label: str
    kind: str  # "opencv" | "realesrgan"
    scale: int
    model_file: Optional[str] = None   # kind == "opencv"
    algo_name: Optional[str] = None    # kind == "opencv"
    model_name: Optional[str] = None   # kind == "realesrgan"


MODEL_OPTIONS = [
    ModelOption("FSRCNN x2 (빠름)", "opencv", 2, model_file="FSRCNN_x2.pb", algo_name="fsrcnn"),
    ModelOption("FSRCNN x4 (빠름)", "opencv", 4, model_file="FSRCNN_x4.pb", algo_name="fsrcnn"),
    ModelOption("EDSR x4 (고화질, 느림)", "opencv", 4, model_file="EDSR_x4.pb", algo_name="edsr"),
    ModelOption("Real-ESRGAN x4 (일반 사진, GPU)", "realesrgan", 4, model_name="realesrgan-x4plus"),
    ModelOption("Real-ESRGAN x4 (애니메이션/일러스트)", "realesrgan", 4, model_name="realesrgan-x4plus-anime"),
]


def _load_as_bgr(path: str) -> np.ndarray:
    """경로의 이미지를 OpenCV가 쓰는 BGR ndarray로 읽는다. cv2.imread는 HEIC를
    못 읽으므로, 그 경우만 Pillow(+pillow-heif)로 디코딩한 뒤 변환한다."""
    ext = Path(path).suffix.lower()
    if ext in _HEIC_EXTENSIONS:
        import pillow_heif

        pillow_heif.register_heif_opener()
        with Image.open(path) as img:
            rgb = np.array(img.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # cv2.imread(path)는 Windows에서 경로에 한글 등 비ASCII 문자가 있으면
    # 파일이 실제로 존재해도 None을 반환한다(내부적으로 로케일 인코딩된
    # 경로로 fopen하기 때문). np.fromfile은 파이썬 자체의 유니코드 경로
    # 처리를 쓰므로 이 문제가 없어서, 바이트로 읽은 뒤 imdecode로 우회한다.
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"파일을 읽을 수 없습니다: {exc}") from exc
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다(지원하지 않는 형식이거나 손상된 파일).")
    return img


def _bgr_to_pixmap(img: np.ndarray, max_size: int) -> QPixmap:
    """BGR ndarray를 화면 표시용 QPixmap으로 바꾼다(원본 처리 결과는 그대로 두고
    미리보기만 축소)."""
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
    pixmap = QPixmap.fromImage(qimage.copy())
    return pixmap.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _center_crop_box(h: int, w: int, size: int) -> tuple[int, int, int, int]:
    """원본 중앙에서 (size x size, 이미지보다 크면 이미지 전체)만큼 잘라낼
    좌표(y0, x0, ch, cw)를 계산한다."""
    ch = min(size, h)
    cw = min(size, w)
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    return y0, x0, ch, cw


def _run_realesrgan(model_name: str, scale: int, src: np.ndarray) -> np.ndarray:
    """realesrgan-ncnn-vulkan.exe를 서브프로세스로 돌린다. 이 exe도 OpenCV처럼
    비ASCII 경로에서 문제가 생길 수 있어서, 항상 임시(ASCII) 경로에 입력을 써서
    넘기고 결과도 임시 경로에서 읽어온다."""
    if not REALESRGAN_EXE.exists():
        raise FileNotFoundError(f"Real-ESRGAN 실행 파일을 찾을 수 없습니다: {REALESRGAN_EXE}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        in_path = tmp_dir / "in.png"
        out_path = tmp_dir / "out.png"

        ok, buf = cv2.imencode(".png", src)
        if not ok:
            raise ValueError("임시 입력 파일을 만들지 못했습니다.")
        buf.tofile(str(in_path))

        proc = subprocess.run(
            [
                str(REALESRGAN_EXE),
                "-i", str(in_path),
                "-o", str(out_path),
                "-n", model_name,
                "-s", str(scale),
            ],
            cwd=str(REALESRGAN_EXE.parent),  # models/ 폴더를 상대경로로 찾으므로 exe 폴더에서 실행
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Real-ESRGAN 실행 실패: {detail or f'exit code {proc.returncode}'}")

        return _load_as_bgr(str(out_path))


class _UpscaleWorker(QThread):
    """실제 업스케일 연산(OpenCV dnn_superres 또는 Real-ESRGAN 서브프로세스)은
    수 초~수십 초 걸릴 수 있고 진행률도 못 받아온다 — 메인 스레드에서 그대로
    부르면 Qt 이벤트 루프가 막혀 Windows가 "응답 없음"으로 표시하므로, 별도
    스레드로 돌려서 최소한 UI가 계속 반응하는 것으로 "멈춘 게 아님"을 보여준다."""

    succeeded = Signal(np.ndarray, float)
    failed = Signal(str)

    def __init__(self, option: ModelOption, sr, src: np.ndarray, parent=None):
        super().__init__(parent)
        self._option = option
        self._sr = sr
        self._src = src

    def run(self):
        try:
            start = time.perf_counter()
            if self._option.kind == "opencv":
                result = self._sr.upsample(self._src)
            else:
                result = _run_realesrgan(self._option.model_name, self._option.scale, self._src)
            elapsed = time.perf_counter() - start
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result, elapsed)


class UpscalePrototype(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PicMedic 화질 개선 프로토타입 (실험용)")
        self.resize(920, 760)

        self._input_path: str | None = None
        self._src_img: np.ndarray | None = None
        self._result_img: np.ndarray | None = None
        self._sr = cv2.dnn_superres.DnnSuperResImpl_create()
        self._loaded_model_file: str | None = None
        self._worker: _UpscaleWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("화질 개선 프로토타입 — 메인 앱과 분리된 실험용 도구")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        outer.addWidget(title)

        note = QLabel(
            "이 창에서 실험한 결과가 쓸 만하면 메인 PicMedic 앱에 정식으로 넣을지 결정합니다. "
            "원본 파일은 절대 바꾸지 않습니다 — 결과는 항상 새 파일로 저장하세요."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        outer.addWidget(note)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)

        self.open_btn = QPushButton("이미지 열기")
        self.open_btn.clicked.connect(self._on_open_clicked)
        control_row.addWidget(self.open_btn)

        self.model_combo = QComboBox()
        for option in MODEL_OPTIONS:
            self.model_combo.addItem(option.label)
        control_row.addWidget(self.model_combo, stretch=1)

        self.run_btn = QPushButton("업스케일 실행")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._on_run_clicked)
        control_row.addWidget(self.run_btn)

        self.save_btn = QPushButton("다른 이름으로 저장")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save_clicked)
        control_row.addWidget(self.save_btn)

        outer.addLayout(control_row)

        self.status_label = QLabel("이미지를 먼저 열어주세요.")
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        outer.addWidget(self.status_label)

        # 진행률을 알 수 없는 작업이라 range(0,0)로 "불확정" 애니메이션만 보여준다
        # — 있으면 "멈춘 게 아니라 처리 중"이 보임.
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        outer.addWidget(self.progress_bar)

        full_row = QHBoxLayout()
        full_row.setSpacing(16)
        self.before_label = self._make_preview_box("원본 (전체)", PREVIEW_SIZE)
        self.after_label = self._make_preview_box("업스케일 결과 (전체)", PREVIEW_SIZE)
        full_row.addWidget(self.before_label[0], stretch=1)
        full_row.addWidget(self.after_label[0], stretch=1)
        outer.addLayout(full_row)

        crop_caption = QLabel(
            "↓ 공정 비교: 같은 영역을 같은 크기로 맞춰서, \"단순 확대\"와 \"AI 업스케일\"만 다르게 본 결과"
        )
        crop_caption.setStyleSheet(f"color: #666; font-size: 12px; margin-top: 4px;")
        outer.addWidget(crop_caption)

        crop_row = QHBoxLayout()
        crop_row.setSpacing(16)
        self.crop_before_label = self._make_preview_box("단순 확대 (bicubic)", CROP_PREVIEW_SIZE)
        self.crop_after_label = self._make_preview_box("AI 업스케일", CROP_PREVIEW_SIZE)
        crop_row.addWidget(self.crop_before_label[0], stretch=1)
        crop_row.addWidget(self.crop_after_label[0], stretch=1)
        outer.addLayout(crop_row, stretch=1)

    def _make_preview_box(self, title: str, size: int) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        caption = QLabel(title)
        caption.setStyleSheet("font-weight: 600;")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)

        image_label = QLabel("-")
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setFixedSize(size, size)
        image_label.setStyleSheet("color: #999; border: 1px dashed #ccc;")
        layout.addWidget(image_label)
        return frame, image_label

    def _reset_previews(self):
        for _, label in (self.after_label, self.crop_before_label, self.crop_after_label):
            label.setPixmap(QPixmap())
            label.setText("-")

    def _on_open_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 열기",
            "",
            "이미지 파일 (*.jpg *.jpeg *.png *.bmp *.heic *.heif)",
        )
        if not path:
            return

        try:
            img = _load_as_bgr(path)
        except Exception as exc:
            QMessageBox.warning(self, "열기 실패", f"이미지를 열지 못했습니다:\n{exc}")
            return

        self._input_path = path
        self._src_img = img
        self._result_img = None
        self.save_btn.setEnabled(False)
        self.run_btn.setEnabled(True)

        h, w = img.shape[:2]
        self.before_label[1].setPixmap(_bgr_to_pixmap(img, PREVIEW_SIZE))
        self._reset_previews()
        self.status_label.setText(f"{Path(path).name} · {w}×{h} — 모델을 고르고 \"업스케일 실행\"을 누르세요.")

    def _on_run_clicked(self):
        if not self._input_path or self._src_img is None or self._worker is not None:
            return
        option = MODEL_OPTIONS[self.model_combo.currentIndex()]

        try:
            if option.kind == "opencv":
                model_path = MODELS_DIR / option.model_file
                if not model_path.exists():
                    raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_path}")
                if self._loaded_model_file != option.model_file:
                    self._sr.readModel(str(model_path))
                    self._loaded_model_file = option.model_file
                self._sr.setModel(option.algo_name, option.scale)
            else:
                if not REALESRGAN_EXE.exists():
                    raise FileNotFoundError(f"Real-ESRGAN 실행 파일을 찾을 수 없습니다: {REALESRGAN_EXE}")
        except Exception as exc:
            QMessageBox.critical(self, "모델 준비 실패", str(exc))
            return

        # 실제 연산(느릴 수 있음)은 별도 스레드에서 돌려서 창이 "응답 없음"으로
        # 보이지 않게 한다.
        self._set_busy(True, f"{option.label} 처리 중... (창이 잠깐 안 움직여도 진행 중입니다)")
        self._worker = _UpscaleWorker(option, self._sr, self._src_img, self)
        self._worker.succeeded.connect(
            lambda result, elapsed: self._on_upscale_succeeded(option, result, elapsed)
        )
        self._worker.failed.connect(self._on_upscale_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_upscale_succeeded(self, option: ModelOption, result: np.ndarray, elapsed: float):
        self._result_img = result
        h, w = result.shape[:2]
        self.after_label[1].setPixmap(_bgr_to_pixmap(result, PREVIEW_SIZE))
        self.status_label.setText(f"{option.label} 완료 · {w}×{h} · {elapsed:.2f}초")
        self.save_btn.setEnabled(True)
        self._update_crop_comparison(option.scale)

    def _update_crop_comparison(self, scale: int):
        """같은 영역을 (1) 단순 bicubic 확대 (2) AI 업스케일 결과에서 잘라내서
        같은 크기로 나란히 보여준다 — 둘 다 최종 표시 크기가 같아야 "화질
        차이"가 진짜로 보인다(그냥 전체 이미지를 같은 미리보기 박스에 욱여넣으면
        AI 결과도 다시 축소되면서 디테일이 사라져 버림)."""
        if self._src_img is None or self._result_img is None:
            return

        h, w = self._src_img.shape[:2]
        y0, x0, ch, cw = _center_crop_box(h, w, CROP_SIZE)
        src_crop = self._src_img[y0 : y0 + ch, x0 : x0 + cw]

        baseline = cv2.resize(src_crop, (cw * scale, ch * scale), interpolation=cv2.INTER_CUBIC)

        ry0, rx0 = y0 * scale, x0 * scale
        result_crop = self._result_img[ry0 : ry0 + ch * scale, rx0 : rx0 + cw * scale]

        self.crop_before_label[1].setPixmap(_bgr_to_pixmap(baseline, CROP_PREVIEW_SIZE))
        self.crop_after_label[1].setPixmap(_bgr_to_pixmap(result_crop, CROP_PREVIEW_SIZE))

    def _on_upscale_failed(self, message: str):
        QMessageBox.critical(self, "처리 실패", f"업스케일 중 오류가 발생했습니다:\n{message}")

    def _on_worker_finished(self):
        self._worker = None
        self._set_busy(False)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.progress_bar.setVisible(busy)
        self.open_btn.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        self.model_combo.setEnabled(not busy)
        if busy:
            self.save_btn.setEnabled(False)
        if message:
            self.status_label.setText(message)

    def _on_save_clicked(self):
        if self._result_img is None or not self._input_path:
            return
        default_name = f"{Path(self._input_path).stem}_upscaled.png"
        path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", default_name, "PNG (*.png)")
        if not path:
            return

        # cv2.imwrite(path, ...)도 imread와 같은 이유로 한글 등 비ASCII 경로에서
        # 조용히 실패할 수 있어서, imencode + ndarray.tofile로 우회한다.
        ok = False
        success, buf = cv2.imencode(".png", self._result_img)
        if success:
            try:
                buf.tofile(path)
                ok = True
            except OSError:
                ok = False

        if ok:
            QMessageBox.information(self, "저장 완료", f"저장했습니다:\n{path}")
        else:
            QMessageBox.warning(self, "저장 실패", "파일을 저장하지 못했습니다.")


def main():
    app = QApplication(sys.argv)
    window = UpscalePrototype()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
