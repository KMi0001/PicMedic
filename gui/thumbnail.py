"""
gui/thumbnail.py

작은 미리보기 이미지 로더. QImageReader::setScaledSize로 디코딩 단계에서부터
축소해서 읽으므로(전체 해상도로 다 읽은 뒤 scaled()하는 것보다 빠름),
gui/trash_screen.py의 검수 화면처럼 썸네일이 한 번에 여러 개 필요한 곳에서
특히 유리하다. HEIC/HEIF는 Qt가 기본으로 못 읽어서 Pillow로 예외 처리한다
(gui/detail_screen.py::_load_preview와 같은 패턴).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from gui.theme import COLORS

_HEIC_EXTENSIONS = (".heic", ".heif")


def load_thumbnail_qimage(path: str, size: int) -> Optional[QImage]:
    """path의 이미지를 size x size 안에 맞춰 축소한 QImage를 반환한다.
    QPixmap과 달리 QImage는 스레드 세이프해서, 백그라운드 스레드에서 여러
    장을 미리 불러올 때(예: gui/date_organize_screen.py) 이 함수를 쓴다 —
    QPixmap 변환은 반드시 메인(GUI) 스레드에서 해야 한다. 읽을 수 없으면
    (파일 없음/손상/미지원 형식) None."""
    ext = Path(path).suffix.lower()
    image: Optional[QImage] = None
    try:
        if ext in _HEIC_EXTENSIONS:
            from PIL import Image
            from PIL.ImageQt import ImageQt

            with Image.open(path) as img:
                img.load()
                img.thumbnail((size, size))
                image = QImage(ImageQt(img.convert("RGBA")))
        else:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            original = reader.size()
            if original.isValid() and not original.isEmpty():
                reader.setScaledSize(original.scaled(QSize(size, size), Qt.KeepAspectRatio))
            decoded = reader.read()
            if not decoded.isNull():
                image = decoded
    except Exception:
        image = None

    if image is None or image.isNull():
        return None
    return image


def load_thumbnail(path: str, size: int) -> Optional[QPixmap]:
    """load_thumbnail_qimage()의 결과를 QPixmap으로 바꾼다 — 메인(GUI) 스레드
    에서만 호출할 것."""
    image = load_thumbnail_qimage(path, size)
    if image is None:
        return None
    return QPixmap.fromImage(image)


class ClickableThumbnail(QFrame):
    """썸네일 + 파일명 한 칸. 눌리면 clicked를 쏜다(어떤 파일인지는 호출부가
    이미 알고 있으므로 인자 없음) — gui/duplicate_screen.py::_ClickableLabel과
    같은 패턴. gui/date_group_detail_screen.py와 gui/similar_screen.py 둘 다
    필요해져서 공용으로 옮김. set_active()로 테두리를 강조할 수 있다(현재
    미리보기에 떠 있는 사진 표시 등 — 안 쓰면 그냥 무시해도 됨)."""

    clicked = Signal()

    def __init__(self, pixmap: Optional[QPixmap], filename: str, size: int = 96, margin: int = 8, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._size = size
        self._margin = margin
        self.setFixedWidth(size + margin * 2)
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(4)

        self.image_label = QLabel()
        self.image_label.setFixedSize(size, size)
        self.image_label.setAlignment(Qt.AlignCenter)
        if pixmap is not None:
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setStyleSheet(f"background-color: {COLORS['border']};")
        layout.addWidget(self.image_label)

        name_label = QLabel(filename)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10.5px;")
        layout.addWidget(name_label)

        self._apply_style()

    def set_active(self, active: bool):
        self._active = active
        self._apply_style()

    def _apply_style(self):
        if self._active:
            self.setStyleSheet(
                f"background-color: {COLORS['selection']}; border: 2px solid {COLORS['primary']}; "
                f"border-radius: 8px;"
            )
        else:
            self.setStyleSheet("border: 2px solid transparent; border-radius: 8px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if not self._active:
            self.setStyleSheet(f"background-color: {COLORS['bg']}; border: 2px solid transparent; border-radius: 8px;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style()
        super().leaveEvent(event)
