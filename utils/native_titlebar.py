"""
utils/native_titlebar.py

Windows 11(DWM) 전용: 네이티브 타이틀바 색을 앱 팔레트에 맞춘다. 타이틀바는
OS가 직접 그리는 영역이라 QSS로 건드릴 수 없어서 DwmSetWindowAttribute를
직접 호출한다 — CLAUDE.md의 "OS별로 코드를 분기하지 않는다" 원칙에 대한
최소 범위 예외(experiments/titlebar_color_prototype에서 실제 스크린샷으로
검증받은 안, 2026-09-10). Windows 10/macOS 등 지원하지 않는 환경에서는
조용히 아무것도 하지 않는다.
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QWidget

_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _to_colorref(hex_color: str) -> int:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r | (g << 8) | (b << 16)


def apply_titlebar_theme(window: QWidget, bg_hex: str, text_hex: str) -> None:
    """window의 네이티브 타이틀바를 bg_hex/text_hex로 칠한다. Windows 11 미만이거나
    macOS/Linux면(DWM이 이 속성을 모름) 예외 없이 그냥 무시되고 기본 타이틀바로
    남는다."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi
        bg = ctypes.c_uint(_to_colorref(bg_hex))
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_CAPTION_COLOR, ctypes.byref(bg), ctypes.sizeof(bg)
        )
        text = ctypes.c_uint(_to_colorref(text_hex))
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), _DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text)
        )
    except OSError:
        pass
