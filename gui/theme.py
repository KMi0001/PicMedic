"""
gui/theme.py

전체 화면에서 공통으로 쓰는 색상/스타일시트(QSS).

다크모드: COLORS는 항상 "지금 켜진 팔레트"를 담은 같은 dict 객체를 가리킨다 —
set_dark_mode()가 이 객체의 내용물만 clear()/update()로 바꿔치기하므로,
`from gui.theme import COLORS`로 이 dict를 가져다 쓰는 모든 화면 파일에서
호출 시점마다 COLORS['xxx']를 읽기만 하면(변수에 미리 캐싱하지만 않으면)
따로 손댈 필요 없이 새 팔레트가 반영된다. 반면 APP_STYLESHEET처럼 f-string으로
한 번에 굳혀놓는 문자열은 그럴 수 없어서 get_stylesheet() 함수로 바꿨다 —
토글 시점에 새로 만들어서 열려있는 모든 창에 다시 적용한다(_refresh_open_windows).
"""

from PySide6.QtCore import QSettings

from utils.assets import asset_path

LIGHT_COLORS = {
    # 버터 · 아이보리 · 톤온톤 잉크 테마
    "bg": "#F7F1E4",
    "surface": "#FFFDF8",
    "border": "#E6DCC5",
    "text": "#2A2420",
    "text_secondary": "#7A7060",
    "primary": "#D9B54A",
    "primary_hover": "#C6A23A",
    "success": "#6E7F4E",
    "warning": "#B97A3A",
    "danger": "#A6453A",
    "muted": "#A79A82",
    "selection": "#F1E6C6",
    "dashed": "#D8C9A0",
    "on_primary": "#2A2420",
}

DARK_COLORS = {
    # 같은 버터 골드 포인트 컬러를 유지한 채 톤온톤 잉크를 어둡게 뒤집은 팔레트.
    "bg": "#1E1A15",
    "surface": "#2A241C",
    "border": "#3D362A",
    "text": "#EDE6D6",
    "text_secondary": "#A79A82",
    "primary": "#D9B54A",
    "primary_hover": "#E8C765",
    "success": "#8FA06B",
    "warning": "#D4934F",
    "danger": "#C77A6C",
    "muted": "#7A7060",
    "selection": "#3A3222",
    "dashed": "#4A4230",
    # 버튼 배경(primary, 골드)이 두 테마에서 똑같은 값이라 그 위에 얹는 글자색도
    # 고정 — light COLORS['text']를 따라가게 두면 다크모드에서 밝은 글자가
    # 골드 배경 위에 올라가 대비가 떨어진다(2026-09-10, 사용자 리포트).
    "on_primary": "#2A2420",
}

_SETTINGS_KEY = "appearance/dark_mode"


def _load_dark_preference() -> bool:
    settings = QSettings("PicMedic", "PicMedic")
    return bool(settings.value(_SETTINGS_KEY, False, type=bool))


def _save_dark_preference(dark: bool) -> None:
    settings = QSettings("PicMedic", "PicMedic")
    settings.setValue(_SETTINGS_KEY, dark)


_dark_mode = _load_dark_preference()

# 다른 파일들이 `from gui.theme import COLORS`로 가져가는 바로 그 dict 객체.
# 재할당하지 않고 내용물만 바꿔치기해야 이미 import해간 곳에서도 갱신이 보인다.
COLORS = dict(DARK_COLORS if _dark_mode else LIGHT_COLORS)


def is_dark_mode() -> bool:
    return _dark_mode


def _build_status_colors() -> dict:
    return {
        "정상": COLORS["success"],
        "형식_불일치": COLORS["warning"],
        "부분_손상": COLORS["warning"],
        "손상": COLORS["danger"],
        "지원되지_않는_형식": COLORS["muted"],
        "이미지가_아닌_파일": COLORS["muted"],
        "알_수_없음": COLORS["muted"],
        "복구_완료": COLORS["primary"],
    }


# COLORS와 같은 이유로 재할당 대신 내용물만 바꿔치기(STATUS_COLORS.clear()/update()).
STATUS_COLORS = _build_status_colors()

STATUS_DOT = {
    "정상": "●",              # ●
    "형식_불일치": "⚠",        # ⚠
    "부분_손상": "⚠",
    "손상": "●",
    "지원되지_않는_형식": "○",  # ○
    "이미지가_아닌_파일": "○",
    "알_수_없음": "○",
    "복구_완료": "✓",          # ✓
}

# QComboBox 드롭다운 버튼(화살표) 아이콘. Qt 스타일시트의 url()은 data: URI를
# 지원하지 않아(실제 그려보면 이미지가 비어 보임) assets/combo_arrow.png 실제 파일을
# 참조해야 한다 — 흰색 삼각형, gui/home_screen.py의 icon.png와 같은 방식으로
# asset_path()를 통해 개발/PyInstaller 빌드 양쪽에서 경로를 구한다.
# Qt QSS의 url()은 백슬래시를 이스케이프로 해석하므로 슬래시로 바꿔준다.
_COMBO_ARROW_URL = asset_path("combo_arrow.png").replace("\\", "/")


def get_stylesheet() -> str:
    """지금 켜진 팔레트(COLORS)로 QSS를 새로 만들어 반환 — 다크모드 토글마다 다시
    호출해서 열려있는 모든 창에 setStyleSheet()로 재적용한다."""
    return _build_stylesheet()


def _build_stylesheet() -> str:
    return f"""
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    font-size: 13px;
}}

/* QLabel/QRadioButton/QCheckBox는 카드(흰 배경) 위에도 자주 올라가는데, 위 QWidget
   규칙 때문에 배경 지정을 안 해주면 각자 앱 기본 배경(아이보리)을 칠해버려서 흰 카드 위에
   얼룩진 띠처럼 보인다. 기본값을 투명으로 깔아서 이 종류의 버그를 원천 차단한다. */
QLabel, QRadioButton, QCheckBox {{
    background-color: transparent;
}}

QLabel#Title {{
    font-size: 22px;
    font-weight: 600;
    color: {COLORS['text']};
}}

QLabel#Subtitle {{
    font-size: 13px;
    color: {COLORS['text_secondary']};
}}

QFrame#Card {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}

QFrame#Card[clickable="true"]:hover {{
    border-color: {COLORS['primary']};
}}

/* 카드형 필터(gui/result_screen.py 요약 칩)로 쓰일 때, 지금 선택된 필터 칩을
   테두리로 표시한다. */
QFrame#Card[selected="true"] {{
    border: 2px solid {COLORS['primary']};
    background-color: {COLORS['selection']};
}}

QPushButton {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 16px;
}}

QPushButton:hover {{
    border-color: {COLORS['primary']};
}}

QPushButton#Primary {{
    background-color: {COLORS['primary']};
    color: {COLORS['on_primary']};
    border: none;
    font-weight: 600;
    padding: 10px 20px;
}}

QPushButton#Primary:hover {{
    background-color: {COLORS['primary_hover']};
}}

QPushButton#Primary:disabled {{
    background-color: {COLORS['muted']};
    color: {COLORS['on_primary']};
}}

QPushButton#Danger {{
    color: {COLORS['danger']};
}}

QLineEdit, QComboBox {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 6px 10px;
}}

QComboBox {{
    padding-right: 28px;
}}

QComboBox:hover {{
    border-color: {COLORS['primary']};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    margin: 4px;
    border-radius: 5px;
    background-color: {COLORS['primary']};
}}

QComboBox::drop-down:hover {{
    background-color: {COLORS['primary_hover']};
}}

QComboBox::down-arrow {{
    image: url({_COMBO_ARROW_URL});
    width: 9px;
    height: 9px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    outline: none;
    selection-background-color: {COLORS['selection']};
    selection-color: {COLORS['text']};
    padding: 4px;
}}

QProgressBar {{
    background-color: {COLORS['border']};
    border: none;
    border-radius: 8px;
    height: 14px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS['primary']};
    border-radius: 8px;
}}

QTableWidget {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['selection']};
    selection-color: {COLORS['text']};
}}

QTableWidget::item {{
    padding: 4px 6px;
    border: none;
}}

QTableWidget::item:selected {{
    background-color: {COLORS['selection']};
    color: {COLORS['text']};
}}

QTableWidget::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLORS['border']};
    border-radius: 4px;
    background-color: {COLORS['surface']};
}}

QTableWidget::indicator:checked {{
    border: 4px solid {COLORS['surface']};
    background-color: {COLORS['primary']};
    border-radius: 4px;
}}

QRadioButton, QCheckBox {{
    spacing: 8px;
}}

QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLORS['border']};
    background-color: {COLORS['surface']};
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator {{
    border-radius: 4px;
}}

QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border-color: {COLORS['primary']};
}}

QRadioButton::indicator:checked {{
    border: 2px solid {COLORS['primary']};
    background-color: qradialgradient(
        cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {COLORS['primary']},
        stop:0.45 {COLORS['primary']},
        stop:0.55 {COLORS['surface']},
        stop:1 {COLORS['surface']}
    );
}}

QCheckBox::indicator:checked {{
    border: 4px solid {COLORS['surface']};
    background-color: {COLORS['primary']};
    border-radius: 4px;
}}

QHeaderView::section {{
    background-color: {COLORS['bg']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 6px;
    font-weight: 600;
}}

QListWidget {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

/* QWidget{{}} 규칙 때문에 QMenu도 스타일시트 렌더링으로 바뀌는데, QMenu::item에
   자체 padding을 안 주면 Qt가 텍스트 폭만큼만 좁게 잡아서 글자가 오른쪽 끝에
   붙어 잘린 것처럼 보인다(우클릭 메뉴에서 확인됨) — 넉넉한 padding으로 고친다. */
QMenu {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 6px;
}}

QMenu::item {{
    padding: 8px 32px 8px 16px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background-color: {COLORS['selection']};
    color: {COLORS['text']};
}}

QMenu::item:disabled {{
    color: {COLORS['muted']};
}}

QMenu::separator {{
    height: 1px;
    background: {COLORS['border']};
    margin: 4px 8px;
}}

/* 기본 OS 스크롤바가 두껍고 각져서 카드/둥근 모서리 톤과 안 맞는다는
   피드백(2026-09-18) — 얇고 둥근 "떠 있는" 핸들 스타일로 통일. 트랙은
   투명(배경이 그대로 비침), 핸들만 은은하게 보이다가 hover/드래그 시
   primary색으로 강조된다. */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    border-radius: 4px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed {{
    background: {COLORS['primary']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    border: none;
    background: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {COLORS['border']};
    border-radius: 4px;
    min-width: 28px;
}}

QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:pressed {{
    background: {COLORS['primary']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    border: none;
    background: none;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""


# experiments/* 프로토타입들이 여전히 `from gui.theme import APP_STYLESHEET`로
# 가져다 쓰므로 import 시점 스냅샷을 하나 남겨둔다 — 실제 앱(gui/main_window.py,
# gui/scan_session_window.py)은 토글 후에도 최신 팔레트를 받도록 get_stylesheet()를
# 직접 호출한다.
APP_STYLESHEET = get_stylesheet()


def set_dark_mode(dark: bool) -> None:
    global _dark_mode
    _dark_mode = dark
    COLORS.clear()
    COLORS.update(DARK_COLORS if dark else LIGHT_COLORS)
    STATUS_COLORS.clear()
    STATUS_COLORS.update(_build_status_colors())
    _save_dark_preference(dark)
    _refresh_open_windows()


def _refresh_open_windows() -> None:
    from PySide6.QtWidgets import QApplication

    from utils.native_titlebar import apply_titlebar_theme

    app = QApplication.instance()
    if app is None:
        return
    stylesheet = get_stylesheet()
    for widget in app.topLevelWidgets():
        # setStyleSheet()를 한 번이라도 받았던(=앱 테마를 쓰는) 최상위 창만 다시 칠한다.
        if widget.styleSheet():
            widget.setStyleSheet(stylesheet)
            apply_titlebar_theme(widget, COLORS["bg"], COLORS["text"])
