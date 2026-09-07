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

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QVBoxLayout

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


class ThumbnailLoadWorker(QThread):
    """paths를 백그라운드에서 한 장씩 QImage로 불러와 thumbnail_ready로 돌려준다
    (QImage는 스레드 세이프, QPixmap 변환은 메인 스레드에서 — 위 설명 참고).
    다 끝나길 기다리지 않고 로드되는 대로 화면에 바로 반영할 수 있다.

    호출부가 지키면 좋은 것: paths는 반드시 "화면에 보이는 순서"로 넘길 것 —
    이 순서 그대로 로딩되므로, 아무 순서(예: 폴더 탐색 순서)로 넘기면 실제로
    보이는 항목보다 안 보이는 항목이 먼저 채워져서 "안 불러와지는 것처럼"
    보이는 문제가 있다(gui/trash_screen.py에서 실사용 중 발견됨).

    gui/trash_screen.py, gui/date_group_detail_screen.py 둘 다 필요해져서
    공용으로 옮김(DESIGN.md "두 번째로 같은 게 필요해지면 공용으로 옮긴다")."""

    thumbnail_ready = Signal(str, object)  # path str, QImage | None

    def __init__(self, paths: list, size: int, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.size = size
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        for path in self.paths:
            if self._cancel_requested:
                break
            path = Path(path)
            image = load_thumbnail_qimage(str(path), self.size) if path.exists() else None
            self.thumbnail_ready.emit(str(path), image)


class ClickableThumbnail(QFrame):
    """썸네일 + 파일명 한 칸. 눌리면 clicked를 쏜다(어떤 파일인지는 호출부가
    이미 알고 있으므로 인자 없음) — gui/duplicate_screen.py::_ClickableLabel과
    같은 패턴. gui/date_group_detail_screen.py와 gui/similar_screen.py 둘 다
    필요해져서 공용으로 옮김. set_active()로 테두리를 강조할 수 있다(현재
    미리보기에 떠 있는 사진 표시 등 — 안 쓰면 그냥 무시해도 됨)."""

    clicked = Signal()
    inclusion_changed = Signal(bool)  # checkable=True일 때만 의미 있음

    def __init__(
        self,
        pixmap: Optional[QPixmap],
        filename: str,
        size: int = 96,
        margin: int = 8,
        parent=None,
        checkable: bool = False,
    ):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._size = size
        self._margin = margin
        self.setFixedWidth(size + margin * 2)
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(4)

        # 정리 대상에서 사진 하나만 빼고 싶을 때(gui/date_group_detail_screen.py)만
        # 켠다 — 기본값 False라 gui/similar_screen.py 등 기존 사용처는 그대로.
        self.include_checkbox: Optional[QCheckBox] = None
        if checkable:
            self.include_checkbox = QCheckBox()
            self.include_checkbox.setChecked(True)
            self.include_checkbox.setStyleSheet("font-size: 10px;")
            self.include_checkbox.toggled.connect(self.inclusion_changed.emit)
            layout.addWidget(self.include_checkbox, alignment=Qt.AlignHCenter)

        self.image_label = QLabel()
        self.image_label.setFixedSize(size, size)
        self.image_label.setAlignment(Qt.AlignCenter)
        self._has_pixmap = pixmap is not None
        if pixmap is not None:
            self.image_label.setPixmap(pixmap)
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

    def is_included(self) -> bool:
        """checkable=False로 만들었으면 항상 True(제외 개념 자체가 없음)."""
        return self.include_checkbox is None or self.include_checkbox.isChecked()

    def set_included(self, included: bool) -> None:
        if self.include_checkbox is not None:
            self.include_checkbox.setChecked(included)

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        """생성 시 None으로 뒀던(아직 배경 스레드 로딩 전) 자리에 나중에 실제
        썸네일을 채워 넣는다 — gui/date_group_detail_screen.py처럼 카드를
        먼저 보여주고 썸네일을 나중에 채우는 화면에서 쓴다."""
        self._has_pixmap = pixmap is not None
        if pixmap is not None:
            self.image_label.setPixmap(pixmap)
        self._apply_style()

    def _apply_style(self):
        # 선택/호버 테두리는 사진 영역(image_label)에만 준다 — 예전엔 셀
        # 전체(체크박스+사진+파일명)를 감싸서 어색해 보였다(사용자 피드백).
        # 사진이 아직 없으면(백그라운드 로딩 중) placeholder 배경도 같이
        # 여기서 계산한다 — set_pixmap()이 별도로 스타일을 덮어쓰면 선택
        # 상태가 지워지는 문제가 있어 하나로 합쳤다.
        if self._active:
            style = (
                f"background-color: {COLORS['selection']}; "
                f"border: 2px solid {COLORS['primary']}; border-radius: 8px;"
            )
        elif not self._has_pixmap:
            style = f"background-color: {COLORS['border']}; border: 2px solid transparent; border-radius: 8px;"
        else:
            style = "border: 2px solid transparent; border-radius: 8px;"
        self.image_label.setStyleSheet(style)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if not self._active:
            self.image_label.setStyleSheet(
                f"background-color: {COLORS['bg']}; border: 2px solid transparent; border-radius: 8px;"
            )
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style()
        super().leaveEvent(event)
