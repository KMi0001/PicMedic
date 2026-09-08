"""
experiments/viewer_redesign_prototype/app.py

목업 전용 — 실제 본체에는 아직 반영 안 함. gui/image_viewer.py의 미리보기를
(1) 카드 테두리 없이 사진을 배경에 바로 중앙 정렬로 띄우고,
(2) 회전/맞추기 버튼 바를 사진 위에 반투명하게 오버레이하는 방향으로 바꿔보면
어떨지 확인하기 위한 것. gui/theme.py의 실제 COLORS/APP_STYLESHEET를 그대로
import해서 색감은 본체와 동일하게 맞췄다(실험용 색을 새로 만들지 않음).

본체에 있는 줌/팬/회전 로직(_ZoomPanView)은 그대로 두고, 이 프로토타입은
레이아웃/오버레이 배치만 다르게 구성한 자리표시자 위젯으로 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QVBoxLayout, QWidget

from gui.theme import APP_STYLESHEET, COLORS


def _fake_photo(w: int, h: int) -> QPixmap:
    """실제 사진 대신 그럴듯한 그라데이션 이미지를 만들어 목업에 쓴다."""
    pm = QPixmap(w, h)
    painter = QPainter(pm)
    gradient = QLinearGradient(0, 0, w, h)
    gradient.setColorAt(0.0, QColor("#8FA6C9"))
    gradient.setColorAt(0.5, QColor("#D8C7A1"))
    gradient.setColorAt(1.0, QColor("#B7876B"))
    painter.fillRect(0, 0, w, h, gradient)
    painter.end()
    return pm


class MockupPanel(QWidget):
    """가운데 사진 + 그 위에 얹힌 반투명 툴바.

    지금 본체(gui/image_viewer.py)는 위쪽에 별도 줄로 버튼 3개를 두고 있어서
    "틀"처럼 느껴진다는 피드백 — 여기서는 버튼 줄을 없애고, 사진 하단 중앙에
    반투명 알약 모양 툴바로 얹어본다.
    """

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setStyleSheet(f"background-color: {COLORS['bg']};")

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)

        self.toolbar = QWidget(self)
        self.toolbar.setObjectName("OverlayToolbar")
        self.toolbar.setStyleSheet(
            "QWidget#OverlayToolbar {"
            " background-color: rgba(20, 18, 15, 150);"
            " border-radius: 20px;"
            "}"
            "QToolButton {"
            " background: transparent;"
            " border: none;"
            " color: white;"
            " font-size: 15px;"
            " padding: 6px 10px;"
            "}"
            "QToolButton:hover {"
            f" background-color: rgba(255,255,255,40);"
            " border-radius: 10px;"
            "}"
        )
        bar_layout = QVBoxLayout(self.toolbar)
        bar_layout.setContentsMargins(6, 4, 6, 4)
        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout()
        row.setSpacing(2)
        # 실제 본체(gui/image_viewer.py)는 ⟲/⟳/⤢ 글자를 쓰는데, 이 헤드리스
        # 목업 환경 폰트엔 그 글리프가 없어 빈 네모로 보인다 — 목업 확인
        # 목적상 알파벳으로 대체(실제 반영 시엔 본체 글자 그대로 씀).
        for glyph, tip in (("L", "왼쪽으로 회전"), ("R", "오른쪽으로 회전"), ("Fit", "화면에 맞추기")):
            btn = QToolButton()
            btn.setText(glyph)
            btn.setToolTip(tip)
            row.addWidget(btn)
        bar_layout.addLayout(row)

        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        self.image_label.setGeometry(self.rect())
        scaled = self._pixmap.scaled(
            self.width() - 40, self.height() - 40, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)

        # 툴바를 패널 전체가 아니라, 실제로 그려진 사진 영역 기준으로 그
        # 하단에 겹치게 배치한다("사진 안쪽에" 반투명하게 보이길 원한다는
        # 요청) — 패널 바닥이 아니라 사진의 바닥에 붙어야 한다.
        img_w, img_h = scaled.width(), scaled.height()
        img_x = (self.width() - img_w) // 2
        img_y = (self.height() - img_h) // 2

        self.toolbar.adjustSize()
        x = img_x + (img_w - self.toolbar.width()) // 2
        y = img_y + img_h - self.toolbar.height() - 14
        self.toolbar.move(x, y)
        self.toolbar.raise_()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)

    panel = MockupPanel(_fake_photo(1600, 1200))
    panel.resize(420, 460)
    panel.setWindowTitle("뷰어 목업 — 틀 없이 중앙 정렬 + 반투명 툴바")
    panel.show()

    out_path = Path(__file__).resolve().parent / "mockup_screenshot.png"
    app.processEvents()
    pixmap = panel.grab()
    pixmap.save(str(out_path))
    print(f"saved: {out_path}")

    if "--interactive" in sys.argv:
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
