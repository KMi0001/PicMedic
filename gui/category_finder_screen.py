"""
gui/category_finder_screen.py

Phase 2 "사진 정리" — 카테고리별 "찾기" 화면 공용 컴포넌트("동물친구들",
"음식 사진", "스크린샷/문서", "야경 사진", "풍경 사진"). core/category_finder.py의
CategoryDef(제목/안내문구/CLIP 프롬프트)로 파라미터화해서 카테고리마다 화면을
따로 만들지 않고 이 클래스 하나를 category_id로 여러 번 인스턴스화한다
(2026-09-11, 사용자 요청 — "동물친구들"만 있던 gui/cat_finder_screen.py를
카테고리 4개 더 추가하면서 이 파일로 일반화함).

지우거나 옮기는 정리 기능이 아니라 "찾아서 보여주기"만 하는 화면이라
gui/duplicate_screen.py·similar_screen.py와 달리 체크박스/라디오가 없다 —
행을 눌러(또는 우클릭 미리보기로) 사진을 확인하는 것만 지원한다. 표 컬럼
구성(파일명(로컬주소)/우클릭 메뉴)은 gui/duplicate_screen.py의 통일된 표
스타일을 따른다.

CLIP 분류는 정답이 아니라 추정이라 오탐/누락이 있을 수 있음을 화면에 안내
문구로 명시한다(core/photo_category.py의 카테고리 판단과 같은 성격).

계산(사진마다 CLIP 추론)이 사진 수에 비례해 오래 걸릴 수 있어(GPU 없는
기기는 특히) 백그라운드 스레드에서 돌리고 진행률 팝업을 보여준다
(gui/similar_screen.py와 같은 패턴). 이미 다른 카테고리 화면이 같은 사진을
본 적 있으면 core/image_embedding_cache.py 캐시 덕분에 그만큼 빨라진다.

"이 방식대로 정리하기"(복사/이동 + 저장 위치 + 실행 버튼, 2026-09-10)는
gui/date_organize_screen.py·city_organize_screen.py와 같은 위젯 구성/문구를
따른다. 날짜별/도시별과 달리 찾은 사진을 그룹으로 더 나누지 않고 폴더
하나로 모은다(core/date_organizer.py::organize_category_finder_results) —
실제 복사/이동은 gui/scan_session_window.py가 실행한다(뷰어와 실행의 분리
원칙은 동일).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QLabel,
    QMenu,
    QPushButton,
    QFrame,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)

from core.category_finder import CATEGORIES, detect, is_available
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.image_viewer import ImageViewer
from gui.organize_settings_dialog import OrganizeSettingsDialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS

CONFIDENCE_COLUMN_WIDTH = 90


def _finder_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 돋보기(원 + 손잡이)로 "AI가 찾아준다"는 걸
    표현한다. 카테고리마다 다른 아이콘을 새로 그리는 대신 이 화면 공통
    아이콘 하나를 쓴다(gui/similar_screen.py::_similar_icon_pixmap과 같은
    아웃라인 스트로크 스타일)."""
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

    painter.drawEllipse(QRectF(3 * scale, 3 * scale, 12 * scale, 12 * scale))
    painter.drawLine(QPointF(12.5 * scale, 12.5 * scale), QPointF(20 * scale, 20 * scale))
    painter.end()
    return pixmap


class _CategoryFinderWorker(QThread):
    """readable한 사진마다 core/category_finder.py::detect()를 돌려 이
    카테고리에 맞는 사진만 골라낸다. CLIP 추론(특히 CPU) 자체가 사진 한
    장에도 수백ms~수 초 걸릴 수 있어(core/photo_category.py 실측 참고)
    반드시 백그라운드에서."""

    progress = Signal(int, int)
    finished_batch = Signal(list)  # list[tuple[FileInfo, float]]

    def __init__(self, category_id: str, files: list, parent=None):
        super().__init__(parent)
        self._category_id = category_id
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
                result = detect(self._category_id, info.path)
            except Exception:
                result = None
            if result is not None and result.matched:
                matches.append((info, result.confidence))
            self.progress.emit(idx, total)
        matches.sort(key=lambda pair: pair[1], reverse=True)
        self.finished_batch.emit(matches)


class CategoryFinderScreen(QWidget):
    """"정리" 허브의 카테고리 카드(동물친구들/음식 사진/스크린샷/야경/풍경)로
    들어오는 화면 — category_id로 core/category_finder.CATEGORIES에서 제목·
    안내문구·프롬프트를 가져온다. 같은 스캔 세션(gui/scan_session_window.py)
    안에서만 쓰인다."""

    back_requested = Signal()
    file_selected = Signal(object, list)  # gui/duplicate_screen.py와 같은 (FileInfo, group) 규약
    organize_requested = Signal(str)  # "copy" | "move" — "이 방식대로 정리하기" 클릭 시점의 방식

    def __init__(self, category_id: str, parent=None):
        super().__init__(parent)
        self.category_id = category_id
        self._category = CATEGORIES[category_id]
        self._matches: list = []  # list[tuple[FileInfo, float]]
        self._worker: _CategoryFinderWorker | None = None
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
        title_icon.setPixmap(_finder_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel(self._category.title)
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

        hint = QLabel(self._category.hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel(self._category.empty_text)
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

        # 표 옆 인라인 미리보기 — gui/result_screen.py 뷰어 패널과 같은 구성
        # (ImageViewer, overlay_controls=True). 예전엔 이 화면에 미리보기가
        # 아예 없어서 행을 확인하려면 더블클릭/우클릭으로 완전히 다른 화면
        # (상세보기)으로 넘어가야 했다(2026-09-18, 사용자 요청 — "정리_동물
        # 친구들~풍경사진 상세 화면에도 미리보기 보여주자"). 더블클릭/우클릭
        # "미리보기"는 기존 그대로 전체 상세 화면을 열고, 행을 한 번 클릭해
        # 선택하면(그 정도로도 충분한 훑어보기용) 이 인라인 패널이 바로
        # 갱신된다.
        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        viewer_panel = QFrame()
        viewer_panel.setObjectName("Card")
        viewer_panel.setFixedWidth(320)
        viewer_layout = QVBoxLayout(viewer_panel)
        viewer_layout.setContentsMargins(4, 4, 4, 4)
        self.inline_viewer = ImageViewer(
            placeholder_text="사진을 선택하면 미리보기가 표시됩니다.", overlay_controls=True
        )
        viewer_layout.addWidget(self.inline_viewer)
        content_row.addWidget(viewer_panel)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["파일명 (로컬주소)", "폴더", "확신도"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, CONFIDENCE_COLUMN_WIDTH)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # 인라인 미리보기를 추가하며 NoSelection -> SingleSelection으로
        # 바꿨다 — 행 클릭이 미리보기를 갱신하려면 선택 상태 자체가 있어야
        # 한다(선택 신호는 itemSelectionChanged로 받음, 아래 connect 참고).
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        # gui/duplicate_screen.py와 같은 이유(2026-09-08) — col이 Stretch라
        # 표 자체의 가로 스크롤은 필요 없고, 켜두면 오른쪽 칸이 숨어 보일 수 있다.
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.table.itemSelectionChanged.connect(self._refresh_inline_viewer)
        content_row.addWidget(self.table, stretch=1)

        outer.addLayout(content_row, stretch=1)

        # --- 하단: "정리하기" 버튼 하나 — gui/date_organize_screen.py와 같은
        # 이유로 정리 방식/파일명/저장 위치는 전부 팝업(OrganizeSettingsDialog)
        # 으로 옮겼다(2026-09-18).
        self._organize_dialog = OrganizeSettingsDialog(
            self,
            title="카테고리 찾기 — 정리하기",
            auto_label="자동 입력 (정리 기준 — 카테고리)",
        )

        self.organize_btn = QPushButton("정리하기")
        self.organize_btn.setObjectName("Primary")
        self.organize_btn.setEnabled(False)
        self.organize_btn.clicked.connect(self._on_organize_clicked)
        outer.addWidget(self.organize_btn)

        self._progress_dialog = ProgressDialog(self)
        self._progress_dialog.cancel_requested.connect(self._on_cancel_requested)

    def set_matches(self, matches: list) -> None:
        """gui/organize_hub_screen.py가 정리 허브 진입 시 이미 백그라운드로
        계산해둔 (FileInfo, confidence) 목록을 그대로 받아 곧장 렌더링한다
        (2026-09-13) — 워커·진행률 팝업 없이 즉시 뜬다. 허브의 계산이 아직
        안 끝났으면 gui/scan_session_category_finder_mixin.py가 이 메서드
        대신 set_result()로 폴백해서 이 화면이 직접 계산하게 한다."""
        self._render_matches(matches)

    def set_result(self, result) -> None:
        """검사 결과를 받아 백그라운드로 이 카테고리 사진을 찾고 화면을 새로
        그린다."""
        if self._worker is not None:
            return

        if not is_available():
            self._render_matches([])
            info_dialog(
                self,
                f"{self._category.title}에 필요한 AI 모델 파일이 아직 준비되지 않았어요.",
            )
            return

        files = list(result.files) if result else []
        self._worker = _CategoryFinderWorker(self.category_id, files, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_batch.connect(self._on_finished)

        self._progress_dialog.start(self._category.searching_label)
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
        self._organize_dialog.set_output_root(path)

    def output_root(self) -> str:
        return self._output_root

    def matched_files(self) -> list:
        """"이 방식대로 정리하기" 실행 대상 — gui/scan_session_window.py가
        core/date_organizer.py::organize_category_finder_results()에 그대로
        넘긴다."""
        return self._all_files()

    def rename_settings(self):
        """gui/date_organize_screen.py::rename_settings()와 같은 역할."""
        return self._organize_dialog.rename_settings()

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
        # setRowCount(0)이 기존 선택을 지우므로, 인라인 미리보기도 같이
        # 비워야 방금 지운 행의 사진이 그대로 남아있지 않는다.
        self._refresh_inline_viewer()

    def _refresh_inline_viewer(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._matches):
            info, _confidence = self._matches[row]
            self.inline_viewer.set_image_path(info.path)
        else:
            self.inline_viewer.set_pixmap(None)

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

    def _on_organize_clicked(self) -> None:
        if self._organize_dialog.exec() != QDialog.Accepted:
            return
        self._output_root = self._organize_dialog.output_root()
        self.organize_requested.emit(self._organize_dialog.mode())
