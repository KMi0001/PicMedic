"""
gui/cat_finder_screen.py

Phase 2 "사진 정리" — "고양이 찾기". 검사된 사진 중 고양이가 나온 사진만
core/cat_finder.py(CLIP zero-shot 분류)로 골라서 표로 보여준다. 지우거나
옮기는 정리 기능이 아니라 "찾아서 보여주기"만 하는 화면이라 gui/duplicate_
screen.py·similar_screen.py와 달리 체크박스/라디오가 없다 — 행을 눌러(또는
우클릭 미리보기로) 사진을 확인하는 것만 지원한다. 표 컬럼 구성(파일명(로컬
주소)/우클릭 메뉴)은 gui/duplicate_screen.py의 통일된 표 스타일을 따른다.

CLIP 분류는 정답이 아니라 추정이라 오탐/누락이 있을 수 있음을 화면에 안내
문구로 명시한다(core/photo_category.py의 카테고리 판단과 같은 성격).

계산(사진마다 CLIP 추론)이 사진 수에 비례해 오래 걸릴 수 있어(GPU 없는
기기는 특히) 백그라운드 스레드에서 돌리고 진행률 팝업을 보여준다
(gui/similar_screen.py와 같은 패턴).

2026-09-10, 사용자 요청으로 gui/date_organize_screen.py·city_organize_screen.py
와 같은 "이 방식대로 정리하기"(복사/이동 + 저장 위치 + 실행 버튼)를 추가했다.
날짜별/도시별과 달리 찾은 사진을 그룹으로 더 나누지 않고 폴더 하나로
모은다(core/date_organizer.py::organize_cat_finder_results) — 실제 복사/
이동은 gui/scan_session_window.py가 실행한다(뷰어와 실행의 분리 원칙은
동일).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QButtonGroup,
    QFileDialog,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QFrame,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from core.cat_finder import detect_cat, is_available
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS

CONFIDENCE_COLUMN_WIDTH = 90


def _cat_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 삼각형 귀 두 개 + 얼굴 원으로 고양이를 표현.
    gui/similar_screen.py::_similar_icon_pixmap과 같은 아웃라인 스트로크
    스타일."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    painter.drawEllipse(r(4, 8, 16, 13))
    ear_left = [
        (5 * scale, 10 * scale), (3 * scale, 3 * scale), (9.5 * scale, 8 * scale),
    ]
    ear_right = [
        (19 * scale, 10 * scale), (21 * scale, 3 * scale), (14.5 * scale, 8 * scale),
    ]
    painter.drawPolyline([QPointF(*p) for p in ear_left])
    painter.drawPolyline([QPointF(*p) for p in ear_right])
    painter.end()
    return pixmap


class _CatFinderWorker(QThread):
    """readable한 사진마다 core/cat_finder.py::detect_cat()을 돌려 고양이가
    있는 사진만 골라낸다. CLIP 추론(특히 CPU) 자체가 사진 한 장에도 수백ms~
    수 초 걸릴 수 있어(core/photo_category.py 실측 참고) 반드시 백그라운드에서."""

    progress = Signal(int, int)
    finished_batch = Signal(list)  # list[tuple[FileInfo, float]]

    def __init__(self, files: list, parent=None):
        super().__init__(parent)
        self._files = files
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        matches: list = []
        candidates = [f for f in self._files if f.readable]
        total = len(candidates)
        for idx, info in enumerate(candidates, start=1):
            if self._cancel_requested:
                break
            try:
                result = detect_cat(info.path)
            except Exception:
                result = None
            if result is not None and result.is_cat:
                matches.append((info, result.confidence))
            self.progress.emit(idx, total)
        matches.sort(key=lambda pair: pair[1], reverse=True)
        self.finished_batch.emit(matches)


class CatFinderScreen(QWidget):
    """"정리" 허브의 "고양이 찾기" 카드로 들어오는 화면. 같은 스캔 세션
    (gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    file_selected = Signal(object, list)  # gui/duplicate_screen.py와 같은 (FileInfo, group) 규약
    organize_requested = Signal(str)  # "copy" | "move" — "이 방식대로 정리하기" 클릭 시점의 방식

    def __init__(self, parent=None):
        super().__init__(parent)
        self._matches: list = []  # list[tuple[FileInfo, float]]
        self._worker: _CatFinderWorker | None = None
        self._output_root: str = ""

        # gui/similar_screen.py·duplicate_screen.py와 같은 "가운데 정렬 +
        # 최대폭 고정" 컨테이너 원칙 — 큰 창에서 표만 덩그러니 늘어나는 걸 방지.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(960)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(content, 100)
        root.addStretch(1)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_cat_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("고양이 찾기")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.found_chip = SummaryChip("찾은 사진", COLORS["primary"])
        chips_row.addWidget(self.found_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "사진 속 내용을 AI로 추정해서 고양이가 나온 사진을 찾아요 — 100% 정확하지는 않아서 "
            "놓치거나 잘못 찾은 사진이 있을 수 있어요. 행을 우클릭하면 미리보기/폴더 열기를 할 수 있어요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel("고양이가 나온 사진을 찾지 못했어요.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일명 (로컬주소)", "폴더", "확신도"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, CONFIDENCE_COLUMN_WIDTH)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        # gui/duplicate_screen.py와 같은 이유(2026-09-08) — col이 Stretch라
        # 표 자체의 가로 스크롤은 필요 없고, 켜두면 오른쪽 칸이 숨어 보일 수 있다.
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        outer.addWidget(self.table, stretch=1)

        # --- 하단: 방식 선택 + 저장 위치 + 실행 — gui/date_organize_screen.py와
        # 같은 위젯 구성/문구(복사 기본값, 이동은 경고색). 찾은 사진 전부를
        # 그룹 없이 폴더 하나로 모은다는 점만 다르다.
        mode_card = QFrame()
        mode_card.setObjectName("Card")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(18, 14, 18, 14)
        mode_layout.setSpacing(8)

        mode_label = QLabel("정리 방식")
        mode_label.setStyleSheet("font-weight: 700;")
        mode_layout.addWidget(mode_label)

        mode_group = QButtonGroup(self)
        self.copy_radio = QRadioButton("복사 (원본은 그대로 두고 새 폴더에 사본 생성 — 기본값)")
        self.copy_radio.setChecked(True)
        mode_group.addButton(self.copy_radio)
        mode_layout.addWidget(self.copy_radio)

        self.move_radio = QRadioButton("이동 (원본이 새 폴더로 옮겨지고 원래 위치엔 안 남음)")
        self.move_radio.setStyleSheet(f"color: {COLORS['warning']};")
        mode_group.addButton(self.move_radio)
        mode_layout.addWidget(self.move_radio)

        mode_layout.addSpacing(14)
        output_caption = QLabel("저장 위치")
        output_caption.setStyleSheet("font-weight: 700;")
        mode_layout.addWidget(output_caption)

        output_row = QHBoxLayout()
        change_output_btn = QPushButton("변경")
        change_output_btn.clicked.connect(self._on_change_output_clicked)
        output_row.addWidget(change_output_btn)
        self.output_path_label = QLabel("")
        self.output_path_label.setWordWrap(True)
        self.output_path_label.setStyleSheet("font-size: 12px;")
        output_row.addWidget(self.output_path_label, stretch=1)
        mode_layout.addLayout(output_row)

        outer.addWidget(mode_card)

        self.organize_btn = QPushButton("이 방식대로 정리하기")
        self.organize_btn.setObjectName("Primary")
        self.organize_btn.setEnabled(False)
        self.organize_btn.clicked.connect(self._on_organize_clicked)
        outer.addWidget(self.organize_btn)

        self._progress_dialog = ProgressDialog(self)
        self._progress_dialog.cancel_requested.connect(self._on_cancel_requested)

    def set_result(self, result) -> None:
        """검사 결과를 받아 백그라운드로 고양이 사진을 찾고 화면을 새로 그린다."""
        if self._worker is not None:
            return

        if not is_available():
            self._render_matches([])
            info_dialog(
                self,
                "고양이 찾기에 필요한 AI 모델 파일이 아직 준비되지 않았어요. "
                "'사진 진단'의 카테고리 판단 기능과 같은 자산을 씁니다.",
            )
            return

        files = list(result.files) if result else []
        self._worker = _CatFinderWorker(files, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_batch.connect(self._on_finished)

        self._progress_dialog.start("고양이 찾는 중")
        self._worker.start()
        self._progress_dialog.exec()

    def _on_progress(self, current: int, total: int):
        self._progress_dialog.update_progress(current, max(total, 1), "사진 분석 중")

    def _on_cancel_requested(self):
        if self._worker is not None:
            self._worker.cancel()

    def _on_finished(self, matches: list):
        self._progress_dialog.accept()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait()
        self._render_matches(matches)

    def set_output_root(self, path: str) -> None:
        self._output_root = path
        self.output_path_label.setText(path)

    def output_root(self) -> str:
        return self._output_root

    def matched_files(self) -> list:
        """"이 방식대로 정리하기" 실행 대상 — gui/scan_session_window.py가
        core/date_organizer.py::organize_cat_finder_results()에 그대로 넘긴다."""
        return self._all_files()

    def _render_matches(self, matches: list) -> None:
        self._matches = matches
        self.found_chip.set_value(len(matches))

        has_any = bool(matches)
        self.empty_label.setVisible(not has_any)
        self.table.setVisible(has_any)
        self.organize_btn.setEnabled(has_any)

        self.table.setRowCount(0)
        self.table.setRowCount(len(matches))
        for row, (info, confidence) in enumerate(matches):
            name_item = QTableWidgetItem(info.filename)
            self.table.setItem(row, 0, name_item)
            folder_item = QTableWidgetItem(str(Path(info.path).parent))
            self.table.setItem(row, 1, folder_item)
            confidence_item = QTableWidgetItem(f"{confidence * 100:.0f}%")
            confidence_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, confidence_item)

    def _all_files(self) -> list:
        return [info for info, _confidence in self._matches]

    def _on_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid() or index.row() >= len(self._matches):
            return
        info, _confidence = self._matches[index.row()]

        menu = QMenu(self)
        preview_action = menu.addAction("미리보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is preview_action:
            self.file_selected.emit(info, self._all_files())
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _on_row_double_clicked(self, index) -> None:
        if not index.isValid() or index.row() >= len(self._matches):
            return
        info, _confidence = self._matches[index.row()]
        self.file_selected.emit(info, self._all_files())

    def _on_change_output_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self._output_root or "")
        if chosen:
            self.set_output_root(chosen)

    def _on_organize_clicked(self) -> None:
        mode = "move" if self.move_radio.isChecked() else "copy"
        self.organize_requested.emit(mode)
