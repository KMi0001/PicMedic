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

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

_HEIC_EXTENSIONS = (".heic", ".heif")


def load_thumbnail(path: str, size: int) -> Optional[QPixmap]:
    """path의 이미지를 size x size 안에 맞춰 축소한 QPixmap을 반환한다.
    읽을 수 없으면(파일 없음/손상/미지원 형식) None."""
    ext = Path(path).suffix.lower()
    pixmap: Optional[QPixmap] = None
    try:
        if ext in _HEIC_EXTENSIONS:
            from PIL import Image
            from PIL.ImageQt import ImageQt

            with Image.open(path) as img:
                img.load()
                img.thumbnail((size, size))
                qimage = ImageQt(img.convert("RGBA"))
                pixmap = QPixmap.fromImage(QImage(qimage))
        else:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            original = reader.size()
            if original.isValid() and not original.isEmpty():
                reader.setScaledSize(original.scaled(QSize(size, size), Qt.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
    except Exception:
        pixmap = None

    if pixmap is None or pixmap.isNull():
        return None
    return pixmap
