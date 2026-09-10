"""
experiments/titlebar_color_prototype/app.py

Windows 11 DWM API(DwmSetWindowAttribute)로 네이티브 타이틀바 색을 앱 다크
팔레트에 맞춰 바꿀 수 있는지 확인하는 프로토타입. 실제 gui/home_screen.py의
HomeScreen을 그대로 띄우고 타이틀바만 DWM으로 칠한다 — 목업이 아니라 실제
화면 + 실제 다크 팔레트로 어떻게 보이는지 사용자가 보고 결정하기 위함
(2026-09-10, "그려줘 보고 결정하자" 요청).

사용법: python experiments/titlebar_color_prototype/app.py
20초 뒤 자동 종료.
"""

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gui import theme
from gui.home_screen import HomeScreen

DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _to_colorref(hex_color: str) -> int:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r | (g << 8) | (b << 16)


def apply_dwm_titlebar(hwnd: int, bg_hex: str, text_hex: str) -> None:
    dwmapi = ctypes.windll.dwmapi
    bg = ctypes.c_uint(_to_colorref(bg_hex))
    dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_CAPTION_COLOR, ctypes.byref(bg), ctypes.sizeof(bg))
    text = ctypes.c_uint(_to_colorref(text_hex))
    dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text))


def main() -> None:
    app = QApplication(sys.argv)
    theme.set_dark_mode(True)

    win = HomeScreen()
    win.setWindowTitle("PicMedic 타이틀바 미리보기 — 사진 진단 · 복구 · 정리")
    win.setStyleSheet(theme.get_stylesheet())
    win.resize(760, 600)
    win.move(80, 80)
    win.show()
    app.processEvents()

    hwnd = int(win.winId())
    apply_dwm_titlebar(hwnd, theme.DARK_COLORS["bg"], theme.DARK_COLORS["text"])
    app.processEvents()

    print(f"READY hwnd={hwnd}", flush=True)

    QTimer.singleShot(20000, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
