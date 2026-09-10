"""
gui/date_group_detail_screen.py

gui/date_organize_screen.py의 그룹 카드를 누르면 여는 화면. 위쪽엔 뷰어
(줌/회전/드래그 이동이 되는 gui/image_viewer.py, 파일명/메타 정보 포함),
아래쪽엔 그 그룹 사진 전체를 썸네일 그리드로 보여준다. 목록에서 사진을
누르면 페이지 이동 없이 위쪽 뷰어가 그 사진으로 바로 바뀐다.

이 화면의 목적은 "정리 실행"이 아니라 "확인 + 골라내기"다 — 뷰어로 사진을
자세히 본 뒤, 이 그룹에서 빼고 싶은 사진은 썸네일의 "포함" 체크를 해제하면
된다(2026-09-07, 사용자 요청 — 뷰어로 살펴본 뒤 일괄 처리). 실제 복사/이동은
여전히 gui/date_organize_screen.py의 "정리하기"에서만 일어나고, 여기서
체크 해제한 사진은 그 실행 대상에서 빠진다. 화질 개선/확장자 변환 같은
편집 액션은 여기 넣지 않는다(그건 gui/detail_screen.py의 역할)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.image_viewer import ImageViewer
from gui.theme import COLORS
from gui.thumbnail import ClickableThumbnail, ThumbnailLoadWorker
from utils.file_utils import format_file_size

THUMB_SIZE = 96
CELL_MARGIN = 8
CELL_SPACING = 12
INFO_COL_WIDTH = 320


class DateGroupDetailScreen(QWidget):
    """gui/date_organize_screen.py 그룹 카드 하나를 눌렀을 때 여는 화면 —
    위: 뷰어(줌/회전 + 이름/메타 정보), 아래: 그룹 전체 목록(포함 체크박스)."""

    back_requested = Signal()
    exclusion_changed = Signal(str, set)  # (그룹 라벨, 제외된 파일 경로 집합)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = ""
        self._files: list = []
        self._excluded: set[str] = set()
        self._cells: list[ClickableThumbnail] = []
        self._last_columns = -1
        # 그룹 안 사진이 많으면(수백 장) 그리드 셀마다 동기 디코딩을 다 돌리면
        # 화면 전환이 멈춘 것처럼 보인다(gui/trash_screen.py에서 같은 문제를
        # 겪고 고친 것과 동일) — 셀은 자리부터 만들어두고 썸네일은 백그라운드
        # 로딩으로 채운다. _thumb_cache는 그룹을 다시 열어도(뒤로 갔다가 다시
        # 클릭) 재사용된다.
        self._thumb_cache: dict[str, object] = {}  # path -> QImage | None
        self._pending_cells: dict[str, list[ClickableThumbnail]] = {}
        self._worker: ThumbnailLoadWorker | None = None
        # QStackedWidget(gui/scan_session_window.py) 안에서 아직 한 번도 안 보인
        # 채로 set_group()이 먼저 불리면, _relayout_grid()가 scroll_area의 낡은
        # (또는 0에 가까운) width로 열 개수를 계산해버려 썸네일이 한 줄에 몰려
        # 보일 수 있다 — gui/organize_hub_screen.py에서 같은 원인으로 고친 것과
        # 동일한 패턴(2026-09-10, 사용자 리포트 — "이거 계속 재현되고 있어").
        # 처음 실제로 보일 때 한 번 더 강제로 다시 계산한다.
        self._relaid_out_once = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setObjectName("Title")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        back_btn = QPushButton("← 목록으로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        # --- 위: 뷰어(사진 왼쪽 + 이름/메타 정보 오른쪽) ---
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_row = QHBoxLayout(preview_card)
        preview_row.setContentsMargins(20, 20, 20, 20)
        preview_row.setSpacing(20)

        # 화면 전체를 쓰는 레이아웃 — 뷰어는 창을 넓힐수록 같이 커지고, 오른쪽
        # 정보 칸은 폭을 고정(gui/detail_screen.py와 같은 원칙)해서 짧은 메타
        # 정보 몇 줄이 화면 절반을 차지하는 빈 공간으로 늘어나지 않게 한다.
        # 검사결과 목록 인라인 미리보기(gui/result_screen.py)와 같은 스타일로
        # 통일 — 회전/맞추기 버튼을 별도 줄 대신 사진 위에 반투명하게 얹는다
        # (2026-09-08, 사용자 요청 — "미리보기/뷰어는 다 검사결과 목록 미리보기처럼").
        self.preview_image = ImageViewer(
            placeholder_text="미리보기를 생성할 수 없습니다.", overlay_controls=True
        )
        self.preview_image.setMinimumSize(260, 260)
        self.preview_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_row.addWidget(self.preview_image, stretch=1)

        info_wrap = QWidget()
        # 이 QWidget이 바로 옆 QFrame#Card(surface색) 위에 얹히는데, 기본 QWidget
        # 규칙(gui/theme.py)이 COLORS['bg']를 불투명하게 칠해버려서 카드 안에
        # 색이 다른 네모 얼룩처럼 보인다(라이트 테마는 bg/surface가 비슷해 안
        # 보였지만 다크 테마에서 두드러짐, 2026-09-10 사용자 리포트) — 투명하게.
        info_wrap.setStyleSheet("background: transparent;")
        info_wrap.setMaximumWidth(INFO_COL_WIDTH)
        info_col = QVBoxLayout(info_wrap)
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(10)
        info_col.setAlignment(Qt.AlignTop)

        self.filename_label = QLabel("")
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        info_col.addWidget(self.filename_label)

        self.info_grid = QGridLayout()
        self.info_grid.setHorizontalSpacing(14)
        self.info_grid.setVerticalSpacing(6)
        info_col.addLayout(self.info_grid)
        info_col.addStretch(1)

        preview_row.addWidget(info_wrap)
        outer.addWidget(preview_card)

        list_row = QHBoxLayout()
        list_label = QLabel("이 그룹의 사진")
        list_label.setStyleSheet("font-weight: 700;")
        list_row.addWidget(list_label)
        list_row.addStretch(1)
        self.exclude_hint_label = QLabel("")
        self.exclude_hint_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px;")
        list_row.addWidget(self.exclude_hint_label)
        outer.addLayout(list_row)

        self.checkbox_hint = QLabel("체크를 해제하면 이 사진은 \"정리하기\" 대상에서 빠져요.")
        self.checkbox_hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        outer.addWidget(self.checkbox_hint)

        # 날짜별 정리처럼 "정리하기" 실행이 있는 화면에서만 체크박스가 의미가
        # 있다 — gui/city_organize_screen.py처럼 훑어보기 전용으로 재사용할
        # 때는 아무 동작도 안 하는 체크박스를 보여주면 오히려 헷갈린다.
        self._show_checkboxes = True

        # --- 아래: 목록(세로 스크롤만 — 가로 스크롤은 절대 안 생기게 열 개수를
        # 창 너비에 맞춰 다시 계산한다) ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setMinimumHeight(200)
        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(CELL_SPACING)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self._grid_container)
        outer.addWidget(self.scroll_area, stretch=1)

    def set_group(
        self,
        label: str,
        files: list,
        excluded_paths: set[str] | None = None,
        show_checkboxes: bool = True,
        initial_file=None,
    ) -> None:
        """label/files는 호출부의 그룹 그대로(날짜별 정리 또는 도시별 정리
        화면의 현재 목록). excluded_paths는 이전에 이 그룹을 열었을 때 체크
        해제해둔 경로들 — 다시 열어도 유지되도록 호출부가 조회해 넘겨준다.
        initial_file을 주면(도시별 정리처럼 목록에서 특정 사진을 눌러 들어올
        때) 그 사진부터 미리보기에 띄운다 — 생략하면 기존처럼 첫 번째 사진.
        show_checkboxes=False면 체크박스와 안내 문구를 아예 숨긴다(현재는
        날짜별/도시별 둘 다 "정리하기"가 있어 기본값 True로 쓰지만, 훑어보기
        전용 화면이 나중에 생기면 이 옵션을 그대로 쓸 수 있다)."""
        self._label = label
        self._files = files
        self._excluded = set(excluded_paths) if excluded_paths else set()
        self._show_checkboxes = show_checkboxes
        self.checkbox_hint.setVisible(show_checkboxes)
        self._update_title()

        if self._worker is not None:
            # 이전 그룹 로딩이 아직 안 끝났으면 취소만 하고 손을 뗀다 —
            # gui/trash_screen.py::refresh()와 같은 이유(QThread를 실행 중에
            # 강제로 없애면 크래시).
            self._worker.cancel()
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker = None

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cells = []
        self._pending_cells = {}

        for info in files:
            path_str = info.path
            cached = self._thumb_cache.get(path_str) if path_str in self._thumb_cache else None
            pixmap = QPixmap.fromImage(cached) if cached is not None else None
            cell = ClickableThumbnail(
                pixmap, info.filename, size=THUMB_SIZE, margin=CELL_MARGIN, checkable=show_checkboxes
            )
            if show_checkboxes:
                cell.set_included(path_str not in self._excluded)
                cell.inclusion_changed.connect(
                    lambda included, path=path_str: self._on_inclusion_changed(path, included)
                )
            cell.clicked.connect(lambda info=info: self._on_thumbnail_clicked(info))
            self._cells.append(cell)
            if path_str not in self._thumb_cache:
                # _pending_cells는 여기서 채워지는 순서(=화면 그리드 순서)
                # 그대로라, 그 순서를 백그라운드 워커에도 그대로 넘긴다 —
                # 아무 순서로나 로딩하면 화면에 보이는 앞쪽 사진보다 뒤쪽이
                # 먼저 채워져서 "안 불러와지는 것처럼" 보이는 문제가 있다.
                self._pending_cells.setdefault(path_str, []).append(cell)

        if files:
            self._on_thumbnail_clicked(initial_file if initial_file is not None else files[0])

        self._update_exclude_hint()
        self._last_columns = -1  # 새 그룹이니 강제로 다시 배치
        self._relayout_grid()

        missing = list(self._pending_cells.keys())
        if missing:
            self._worker = ThumbnailLoadWorker(missing, THUMB_SIZE, self)
            self._worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._worker.start()

    def stop_pending_work(self) -> None:
        """이 화면을 담은 창이 곧 닫히기 전에 불러서 백그라운드 썸네일 로딩을
        안전하게 멈춘다 — gui/trash_screen.py::stop_pending_work()와 같은 이유
        (QThread가 도는 중에 같이 없어지면 크래시 위험)."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait()
            self._worker = None

    def _on_thumbnail_ready(self, path_str: str, image) -> None:
        self._thumb_cache[path_str] = image
        cells = self._pending_cells.get(path_str)
        if not cells:
            return
        pixmap = QPixmap.fromImage(image) if image is not None else None
        for cell in cells:
            cell.set_pixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_grid()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._relaid_out_once:
            self._relaid_out_once = True
            # 지금 바로 다시 계산하면 아직 QStackedWidget이 이 위젯에 최종
            # geometry를 넘기기 전일 수 있어(같은 이벤트 처리 중) 한 틱 미룬다
            # (gui/organize_hub_screen.py::_force_relayout과 같은 이유).
            QTimer.singleShot(0, self._force_relayout)

    def _force_relayout(self) -> None:
        self._last_columns = -1  # 캐시된 열 개수를 무시하고 강제로 다시 계산
        self._relayout_grid()

    def _relayout_grid(self):
        if not self._cells:
            return

        cell_width = THUMB_SIZE + CELL_MARGIN * 2 + CELL_SPACING
        available = self.scroll_area.viewport().width() or self.width()
        columns = max(1, available // cell_width)
        if columns == self._last_columns:
            return
        self._last_columns = columns

        for cell in self._cells:
            self._grid.removeWidget(cell)
        for idx, cell in enumerate(self._cells):
            self._grid.addWidget(cell, idx // columns, idx % columns)

    def _on_inclusion_changed(self, path: str, included: bool) -> None:
        if included:
            self._excluded.discard(path)
        else:
            self._excluded.add(path)
        self._update_exclude_hint()
        self._update_title()
        self.exclusion_changed.emit(self._label, set(self._excluded))

    def _update_title(self) -> None:
        total = len(self._files)
        excluded = len(self._excluded)
        if excluded:
            count_text = f"{total - excluded}장/{total}장 (제외 {excluded}장)"
        else:
            count_text = f"{total}장"
        self.title_label.setText(f"{self._label} · {count_text}")

    def _update_exclude_hint(self) -> None:
        if self._excluded:
            self.exclude_hint_label.setText(f"{len(self._excluded)}장 제외됨")
        else:
            self.exclude_hint_label.setText("")

    def _on_thumbnail_clicked(self, info) -> None:
        self.preview_image.set_image_path(info.path)

        self.filename_label.setText(info.filename)
        self._set_info_rows(info)

        for cell, file_info in zip(self._cells, self._files):
            cell.set_active(file_info is info)

    def _set_info_rows(self, info) -> None:
        while self.info_grid.count():
            item = self.info_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = []
        if info.width and info.height:
            rows.append(("해상도", f"{info.width} × {info.height}"))
        rows.append(("파일 크기", format_file_size(info.file_size)))
        if info.captured_at:
            rows.append(("촬영일", info.captured_at.strftime("%Y-%m-%d")))

        for row, (label, value) in enumerate(rows):
            label_widget = QLabel(label)
            label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
            value_widget = QLabel(value)
            self.info_grid.addWidget(label_widget, row, 0)
            self.info_grid.addWidget(value_widget, row, 1)
