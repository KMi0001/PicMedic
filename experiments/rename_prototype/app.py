"""
파일명 일괄변경 UI 프로토타입 (독립 실행, 메인 앱 코드 import 없음)

목적: gui/result_screen.py 하단에 추가할 "이름변경" 버튼 + 팝업의 실제 동작을
PySide6로 직접 만들어서 확인하기 위한 throwaway 프로토타입. 값이 확인되면
main 앱(gui/result_screen.py, gui/common_dialogs.py 등)에 통합한다.

실행:
    python experiments/rename_prototype/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# DESIGN.md / gui/theme.py의 "버터 · 아이보리 · 톤온톤 잉크" 팔레트를 그대로 하드코딩.
# (프로토타입은 메인 앱 코드를 import하지 않는다는 원칙 — gui/theme.py를 import하지 않고
#  같은 값만 복사해서 씀)
COLORS = {
    "bg": "#F7F1E4",
    "surface": "#FFFDF8",
    "border": "#E6DCC5",
    "text": "#2A2420",
    "text_secondary": "#7A7060",
    "primary": "#D9B54A",
    "primary_hover": "#C9A53E",
    "on_primary": "#2A2420",
    "selection": "#F1E6C6",
    "muted": "#A79A82",
    "danger": "#A6453A",
}

STYLESHEET = f"""
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    font-size: 13px;
}}
QFrame#Card, QDialog {{
    background-color: {COLORS['surface']};
}}
QTableWidget {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    gridline-color: {COLORS['border']};
}}
QHeaderView::section {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 6px;
    font-weight: 600;
}}
QPushButton {{
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 16px;
    background-color: {COLORS['surface']};
}}
QPushButton#Primary {{
    background-color: {COLORS['primary']};
    color: {COLORS['on_primary']};
    border: none;
    font-weight: 700;
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
QLineEdit, QSpinBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 6px 8px;
    background-color: {COLORS['surface']};
}}
QLabel, QRadioButton, QCheckBox {{
    background-color: transparent;
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
QRadioButton:disabled {{
    color: {COLORS['muted']};
}}
#SectionHeader {{
    font-weight: 700;
    color: {COLORS['text']};
    border-left: 3px solid {COLORS['primary']};
    padding-left: 8px;
}}
#Muted {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
}}
#PreviewRow {{
    color: {COLORS['text_secondary']};
}}
#PreviewArrowNew {{
    color: {COLORS['text']};
    font-weight: 600;
}}
"""

def _outline_icon(color: str, size: int, draw) -> QPixmap:
    """gui/home_screen.py::_outline_icon과 같은 패턴 (스트로크만 있는 벡터 아이콘)."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    draw(painter, scale)
    painter.end()
    return pixmap


def _rename_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """이름 일괄변경 = 이름표(태그) 모양 + 안의 글자 줄 — "이름을 새로 단다"는 의미."""

    def draw(p, s):
        # 태그 몸통 (오각형 느낌으로 오른쪽이 뾰족)
        p.drawLine(QPointF(4 * s, 5 * s), QPointF(15 * s, 5 * s))
        p.drawLine(QPointF(15 * s, 5 * s), QPointF(20 * s, 12 * s))
        p.drawLine(QPointF(20 * s, 12 * s), QPointF(15 * s, 19 * s))
        p.drawLine(QPointF(15 * s, 19 * s), QPointF(4 * s, 19 * s))
        p.drawLine(QPointF(4 * s, 19 * s), QPointF(4 * s, 5 * s))
        # 구멍
        p.drawEllipse(QRectF(6.5 * s, 10.5 * s, 3 * s, 3 * s))
        # 글자 줄(이름이 적힌 부분)
        p.drawLine(QPointF(12 * s, 9 * s), QPointF(17 * s, 9 * s))
        p.drawLine(QPointF(12 * s, 13 * s), QPointF(17 * s, 13 * s))

    return _outline_icon(color, size, draw)


class DropActionCardMock(QFrame):
    """gui/home_screen.py::DropActionCard 스타일 복제(정적 목업, 드래그앤드롭 로직은 생략)."""

    def __init__(self, icon_pixmap: QPixmap, title: str, desc: str, hint: str = "여기로 끌어놓기\n또는 클릭"):
        super().__init__()
        self.setObjectName("Card")
        self.setStyleSheet(
            f"QFrame#Card {{ border: 1px solid {COLORS['border']}; border-radius: 14px; "
            f"background-color: {COLORS['surface']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        icon_label = QLabel()
        icon_label.setFixedSize(52, 52)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"background-color: {COLORS['selection']}; border-radius: 26px;")
        icon_label.setPixmap(icon_pixmap)
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        text_col.addWidget(title_label)
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px; background: transparent;")
        text_col.addWidget(desc_label)
        layout.addLayout(text_col, 1)

        hint_label = QLabel(hint)
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 10.5px; background: transparent;")
        layout.addWidget(hint_label)


def _set_primary_active(button: QPushButton, active: bool) -> None:
    """gui/result_screen.py::_set_primary_active와 동일한 패턴."""
    button.setObjectName("Primary" if active else "")
    button.style().unpolish(button)
    button.style().polish(button)


# 샘플 데이터: (파일명, 상태, 날짜그룹) — 날짜그룹은 "자동 입력" 모드가 쓸 컨텍스트 값
SAMPLE_FILES = [
    ("IMG_2925.PNG", "정상", "2026-08-12"),
    ("IMG_2938.PNG", "정상", "2026-08-12"),
    ("IMG_2973.PNG", "정상", "2026-08-12"),
    ("IMG_2977.PNG", "정상", "2026-08-13"),
    ("IMG_2983.PNG", "정상", "2026-08-13"),
]


class RenameDialog(QDialog):
    """이름 일괄변경 팝업. DESIGN.md의 팝업 패턴(카드형, WindowModal)을 따른다."""

    def __init__(self, parent, selected_files: list[tuple[str, str, str]], start_auto: bool = False):
        super().__init__(parent)
        self.setWindowTitle("이름 일괄변경")
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(420)
        self._files = selected_files

        # 선택 파일들이 같은 정리 그룹(날짜)인지 — 아니면 "자동 입력" 비활성화
        groups = {g for _, _, g in selected_files}
        self._common_group = next(iter(groups)) if len(groups) == 1 else None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("이름 일괄변경")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        # 모드 선택
        mode_row = QHBoxLayout()
        self.radio_manual = QRadioButton("이름 직접 입력")
        self.radio_auto = QRadioButton("자동 입력 (정리 결과)")
        start_auto = start_auto and self._common_group is not None
        self.radio_manual.setChecked(not start_auto)
        self.radio_auto.setChecked(start_auto)
        if self._common_group is None:
            self.radio_auto.setEnabled(False)
            self.radio_auto.setToolTip("선택한 파일이 여러 날짜 그룹에 걸쳐 있어 자동 입력을 쓸 수 없습니다")
        mode_row.addWidget(self.radio_manual)
        mode_row.addWidget(self.radio_auto)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # 이름 입력창
        name_label = QLabel("이름")
        name_label.setObjectName("SectionHeader")
        root.addWidget(name_label)
        self.name_edit = QLineEdit("여행")
        root.addWidget(self.name_edit)

        # 순번 옵션
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("시작 번호"))
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 9999)
        self.start_spin.setValue(1)
        opts_row.addWidget(self.start_spin)
        opts_row.addSpacing(16)
        opts_row.addWidget(QLabel("자릿수"))
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(1, 6)
        self.digits_spin.setValue(3)
        opts_row.addWidget(self.digits_spin)
        opts_row.addStretch(1)
        root.addLayout(opts_row)

        # 미리보기
        preview_label = QLabel(f"미리보기 ({len(selected_files)}개)")
        preview_label.setObjectName("SectionHeader")
        root.addWidget(preview_label)

        self.preview_grid = QGridLayout()
        self.preview_grid.setSpacing(4)
        root.addLayout(self.preview_grid)

        # 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("변경 실행")
        confirm_btn.setObjectName("Primary")
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn)
        root.addLayout(btn_row)

        # 값이 바뀔 때마다 미리보기 갱신
        self.radio_manual.toggled.connect(self._on_mode_changed)
        self.name_edit.textChanged.connect(self._update_preview)
        self.start_spin.valueChanged.connect(self._update_preview)
        self.digits_spin.valueChanged.connect(self._update_preview)

        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        manual = self.radio_manual.isChecked()
        if not manual and self._common_group:
            # setText 자체가 textChanged -> _update_preview를 이미 트리거하므로,
            # 아래 명시적 호출과 중복 실행되지 않도록 일시적으로 신호를 막는다.
            self.name_edit.blockSignals(True)
            self.name_edit.setText(self._common_group)
            self.name_edit.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        # 기존 행 지우기
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        base = self.name_edit.text().strip() or "이름없음"
        start = self.start_spin.value()
        digits = self.digits_spin.value()

        for row, (old_name, _status, _group) in enumerate(self._files):
            ext = Path(old_name).suffix
            number = str(start + row).zfill(digits)
            new_name = f"{base}_{number}{ext}"

            old_label = QLabel(old_name)
            old_label.setObjectName("PreviewRow")
            arrow_label = QLabel("→")
            arrow_label.setObjectName("PreviewRow")
            new_label = QLabel(new_name)
            new_label.setObjectName("PreviewArrowNew")

            self.preview_grid.addWidget(old_label, row, 0)
            self.preview_grid.addWidget(arrow_label, row, 1)
            self.preview_grid.addWidget(new_label, row, 2)


class MockResultScreen(QMainWindow):
    """gui/result_screen.py 하단 액션 바 목업."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("검사 결과 (이름변경 프로토타입)")
        self.resize(640, 420)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("검사 결과")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        # 상태 요약 카드(칩) 행 — 실제로는 gui/result_screen.py::SummaryChip,
        # 여기선 자리만 보여주면 되니 QLabel로 단순화.
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        for chip_text in ["총 파일 5", "정상 5", "형식 불일치 0", "손상 0"]:
            chip = QLabel(chip_text)
            chip.setStyleSheet(
                f"background-color: {COLORS['selection']}; border-radius: 6px; "
                f"padding: 6px 10px; font-size: 11px; font-weight: 600;"
            )
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        hint_label = QLabel("목록에서 우클릭을 해서 로컬폴더로 이동하거나 상세보기를 할 수 있습니다.")
        hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        hint_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        chips_row.addWidget(hint_label)
        layout.addLayout(chips_row)

        self.table = QTableWidget(len(SAMPLE_FILES), 4)
        self.table.setHorizontalHeaderLabels(["", "파일명", "상태", "날짜그룹"])
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 32)
        self.table.horizontalHeader().setStretchLastSection(True)
        self._checkboxes: list[QCheckBox] = []
        for row, (name, status, group) in enumerate(SAMPLE_FILES):
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_selection_label)
            self.table.setCellWidget(row, 0, cb)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(status))
            self.table.setItem(row, 3, QTableWidgetItem(group))
            self._checkboxes.append(cb)
        layout.addWidget(self.table)

        bottom = QHBoxLayout()
        self.selection_label = QLabel()
        bottom.addWidget(self.selection_label)
        bottom.addStretch(1)
        # 실제 화면(gui/result_screen.py:541)엔 "Medic!"이 아니라 "확장자 변환"만
        # 남아있음 — AI 복원 기능들이 다 빠지면서 이름이 바뀜(2026-09-13).
        self.convert_btn = QPushButton("확장자 변환")
        bottom.addWidget(self.convert_btn)
        self.rename_btn = QPushButton("이름일괄변환")
        self.rename_btn.clicked.connect(self._open_rename_dialog)
        bottom.addWidget(self.rename_btn)
        layout.addLayout(bottom)

        self._update_selection_label()

    def _selected_files(self) -> list[tuple[str, str, str]]:
        return [SAMPLE_FILES[i] for i, cb in enumerate(self._checkboxes) if cb.isChecked()]

    def _update_selection_label(self) -> None:
        selected = self._selected_files()
        has_any = bool(selected)
        self.selection_label.setText(f"{len(selected)}개 선택됨" if has_any else "선택된 파일 없음")
        self.convert_btn.setEnabled(has_any)
        self.rename_btn.setEnabled(has_any)
        # "확장자 변환"만 이 화면의 진짜 주요 동작(Primary/채워진 버튼)으로 남기고,
        # "이름일괄변환"은 보조 동작이라 테두리만 있는 기본 버튼 스타일 유지 —
        # 버튼 두 개가 똑같이 채워지면 뭐가 메인 동작인지 헷갈림.
        _set_primary_active(self.convert_btn, has_any)

    def _open_rename_dialog(self) -> None:
        selected = self._selected_files()
        if not selected:
            return
        dialog = RenameDialog(self, selected)
        dialog.exec()


class MockHomeScreen(QMainWindow):
    """gui/home_screen.py 목업 — 기존 검사/변환/라이브포토 카드 옆에 "이름 일괄변환" 카드 추가."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("홈 (이름 일괄변환 카드 프로토타입)")
        self.resize(520, 640)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.setSpacing(16)

        title = QLabel("PicMedic")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        outer.addWidget(title)

        scan_card = DropActionCardMock(
            _rename_icon_pixmap(COLORS["primary"]),  # 임시: 실제론 검사 전용 아이콘
            "검사",
            "사진이나 폴더를 끌어놓으면 검사하고 정리까지 도와드려요.",
        )
        outer.addWidget(scan_card)

        convert_card = DropActionCardMock(
            _rename_icon_pixmap(COLORS["primary"]),  # 임시: 실제론 변환 전용 아이콘
            "변환",
            "사진 형식을 다른 형식으로 바꿔요 (여러 장도 가능)",
        )
        outer.addWidget(convert_card)

        live_photo_card = DropActionCardMock(
            _rename_icon_pixmap(COLORS["primary"]),  # 임시: 실제론 라이브포토 전용 아이콘
            "라이브 포토",
            "짝 동영상이 남아있는 라이브 포토를 찾아서 내보내거나 모아줘요",
        )
        outer.addWidget(live_photo_card)

        rename_card = DropActionCardMock(
            _rename_icon_pixmap(COLORS["primary"]),
            "이름 일괄변환",
            "사진 여러 장의 파일명을 한 번에 바꿔요 (순번 매기기 등)",
        )
        outer.addWidget(rename_card)

        outer.addStretch(1)


class MockOrganizeResultScreen(QMainWindow):
    """정리 결과 화면(gui/duplicate_screen.py 등) 목업 — 하단에 "이름일괄변환" 추가."""

    GROUP_FILES = [
        ("a.jpg", "여행/2026-08-12"),
        ("a_1.jpg", "여행/2026-08-12"),
        ("b.jpg", "여행/2026-08-13"),
        ("b_1.jpg", "여행/2026-08-13"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("중복 사진 (정리 결과 화면 프로토타입)")
        self.resize(640, 420)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("중복 사진")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        table = QTableWidget(len(self.GROUP_FILES), 3)
        table.setHorizontalHeaderLabels(["", "파일명", "폴더"])
        table.verticalHeader().setVisible(False)
        table.setColumnWidth(0, 32)
        table.horizontalHeader().setStretchLastSection(True)
        for row, (name, folder) in enumerate(self.GROUP_FILES):
            cb = QCheckBox()
            cb.setChecked(True)
            table.setCellWidget(row, 0, cb)
            table.setItem(row, 1, QTableWidgetItem(name))
            table.setItem(row, 2, QTableWidgetItem(folder))
        layout.addWidget(table)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        # "정리 실행"과 같은 자리(하단, 화면 폭 기준 오른쪽)에 보조 동작으로 배치.
        rename_btn = QPushButton("이름일괄변환")
        bottom.addWidget(rename_btn)
        cleanup_btn = QPushButton("정리 실행 — 임시 휴지통으로 이동")
        cleanup_btn.setObjectName("Danger")
        bottom.addWidget(cleanup_btn)
        layout.addLayout(bottom)


def build_organize_dialog(parent) -> QDialog:
    """정리 방식 + 파일명 + 저장 위치 전부를 담은 팝업(2026-09-18, 사용자 요청 —
    메인 화면에 설정 카드를 두면 목록 영역이 좁아지니, 전부 팝업으로 빼고
    메인 화면엔 "정리하기" 버튼 하나만 남긴다). 팝업의 "정리 실행" 버튼을
    누르면(accept) 실제 core.date_organizer 호출은 호출부가 이어서 한다."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("날짜별 정리 — 정리하기")
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(10)

    mode_label = QLabel("정리 방식")
    mode_label.setObjectName("SectionHeader")
    layout.addWidget(mode_label)
    copy_radio = QRadioButton("복사 (원본은 그대로 두고 새 폴더에 사본 생성 — 기본값)")
    copy_radio.setChecked(True)
    layout.addWidget(copy_radio)
    move_radio = QRadioButton("이동 (원본이 새 폴더로 옮겨지고 원래 위치엔 안 남음)")
    layout.addWidget(move_radio)

    layout.addSpacing(8)
    filename_label = QLabel("파일명")
    filename_label.setObjectName("SectionHeader")
    layout.addWidget(filename_label)
    keep_radio = QRadioButton("원래 이름 유지 (기본값)")
    keep_radio.setChecked(True)
    rename_radio = QRadioButton("새 이름으로 변경")
    name_group = QButtonGroup(dialog)
    name_group.addButton(keep_radio)
    name_group.addButton(rename_radio)
    layout.addWidget(keep_radio)
    layout.addWidget(rename_radio)

    # 팝업 안이라 공간 여유가 있으니, 이번엔 다시 인라인 2행으로 —
    # 또 한 겹 팝업을 씌우면 클릭이 한 번 더 늘어나서 오히려 번거롭다.
    detail = QWidget()
    detail_layout = QVBoxLayout(detail)
    detail_layout.setContentsMargins(20, 6, 0, 0)
    detail_layout.setSpacing(6)

    row1 = QHBoxLayout()
    manual_radio = QRadioButton("직접 입력")
    manual_radio.setChecked(True)
    auto_radio = QRadioButton("자동 입력 (날짜별)")
    input_group = QButtonGroup(detail)
    input_group.addButton(manual_radio)
    input_group.addButton(auto_radio)
    row1.addWidget(manual_radio)
    row1.addWidget(auto_radio)
    name_edit = QLineEdit("여행")
    row1.addWidget(name_edit, stretch=1)
    detail_layout.addLayout(row1)

    row2 = QHBoxLayout()
    row2.addWidget(QLabel("시작 번호"))
    start_spin = QSpinBox()
    start_spin.setValue(1)
    row2.addWidget(start_spin)
    row2.addSpacing(10)
    row2.addWidget(QLabel("자릿수"))
    digits_spin = QSpinBox()
    digits_spin.setRange(1, 6)
    digits_spin.setValue(3)
    row2.addWidget(digits_spin)
    row2.addSpacing(10)
    preview_label = QLabel("")
    preview_label.setObjectName("Muted")
    row2.addWidget(preview_label, stretch=1)
    detail_layout.addLayout(row2)

    def _update_preview():
        if auto_radio.isChecked():
            name_edit.setEnabled(False)
            base = "2026-08"
        else:
            name_edit.setEnabled(True)
            base = name_edit.text().strip() or "이름없음"
        sample = f"{base}_{str(start_spin.value()).zfill(digits_spin.value())}.jpg"
        preview_label.setText(f"미리보기: {sample}, ...")

    manual_radio.toggled.connect(_update_preview)
    auto_radio.toggled.connect(_update_preview)
    name_edit.textChanged.connect(_update_preview)
    start_spin.valueChanged.connect(_update_preview)
    digits_spin.valueChanged.connect(_update_preview)
    _update_preview()

    layout.addWidget(detail)

    def _toggle_detail(checked: bool) -> None:
        detail.setVisible(checked)

    rename_radio.toggled.connect(_toggle_detail)
    detail.setVisible(False)

    layout.addSpacing(8)
    output_label = QLabel("저장 위치")
    output_label.setObjectName("SectionHeader")
    layout.addWidget(output_label)
    output_row = QHBoxLayout()
    change_btn = QPushButton("변경")
    output_row.addWidget(change_btn)
    output_path = QLabel("사진/PicMedic정리")
    output_path.setStyleSheet("font-size: 12px;")
    output_row.addWidget(output_path, stretch=1)
    layout.addLayout(output_row)

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn = QPushButton("정리 실행")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    confirm_btn.clicked.connect(dialog.accept)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    layout.addLayout(btn_row)

    dialog._rename_radio = rename_radio  # 캡처 스크립트에서 상태 전환용
    return dialog


class MockOrganizeSettingsScreen(QMainWindow):
    """gui/date_organize_screen.py 목업 — 정리 방식/파일명/저장 위치를 전부
    팝업(build_organize_dialog)으로 빼고, 메인 화면엔 그룹 목록 + "정리하기"
    버튼 하나만 남긴다."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("날짜별 정리 (설정 팝업 프로토타입)")
        self.resize(460, 520)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel("날짜별 정리")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        outer.addWidget(title)

        placeholder = QLabel("(그룹 목록 영역 — 설정 카드가 빠진 만큼 넓어짐)")
        placeholder.setObjectName("Muted")
        placeholder.setAlignment(Qt.AlignCenter)
        outer.addWidget(placeholder, stretch=1)

        organize_btn = QPushButton("정리하기")
        organize_btn.setObjectName("Primary")
        organize_btn.clicked.connect(self._open_organize_dialog)
        outer.addWidget(organize_btn)

    def _open_organize_dialog(self):
        dialog = build_organize_dialog(self)
        dialog.exec()


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MockResultScreen()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
