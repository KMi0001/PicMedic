"""
gui/theme.py

전체 화면에서 공통으로 쓰는 색상/스타일시트(QSS).
"""

COLORS = {
    # 민트 케어 테마
    "bg": "#F1F8F5",
    "surface": "#FFFFFF",
    "border": "#DCEAE3",
    "text": "#17332A",
    "text_secondary": "#5E8677",
    "primary": "#12B5A6",
    "primary_hover": "#0E9689",
    "success": "#2FAF66",
    "warning": "#D9A441",
    "danger": "#DA5A5A",
    "muted": "#8FAFA0",
    "selection": "#DCF3E9",
}

STATUS_COLORS = {
    "정상": COLORS["success"],
    "형식_불일치": COLORS["warning"],
    "부분_손상": COLORS["warning"],
    "손상": COLORS["danger"],
    "지원되지_않는_형식": COLORS["muted"],
    "이미지가_아닌_파일": COLORS["muted"],
    "알_수_없음": COLORS["muted"],
    "복구_완료": COLORS["primary"],
}

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

APP_STYLESHEET = f"""
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
    font-size: 13px;
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
    color: white;
    border: none;
    font-weight: 600;
    padding: 10px 20px;
}}

QPushButton#Primary:hover {{
    background-color: {COLORS['primary_hover']};
}}

QPushButton#Primary:disabled {{
    background-color: {COLORS['muted']};
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
"""
