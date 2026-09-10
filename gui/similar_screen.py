"""
gui/similar_screen.py

Phase 2 "사진 정리" — 유사 중복(퍼셉추얼 해시 + 파일명 패턴) 탐지 결과를
보여주고, 완전 중복(gui/duplicate_screen.py)과 같은 방식으로 남길 파일을
고르면 나머지를 임시 휴지통으로 옮긴다. models/scan_result.py::similar_groups()
참고 — 완전 중복(바이트 단위 동일)은 거기서 이미 제외된 상태로 넘어온다.

완전 중복과 다른 점: 오탐 가능성이 있는 "추정"이라서(퍼셉추얼 해시/파일명
패턴 둘 다 휴리스틱), (1) 실제 썸네일을 나란히 보여줘서 사용자가 직접 눈으로
확인하게 하고, (2) 왜 묶였는지(파일명 패턴 / 이미지 유사도 거리)를 같이
보여준다 — "정확도를 직접 판단"할 수 있게. 그룹핑 계산 자체가 사진이 많으면
느릴 수 있어(퍼셉추얼 해시 쌍 비교 O(n^2)) 백그라운드 스레드에서 돌리고,
화면을 여는 동안 진행률 팝업을 보여준다. 완전 중복처럼 모든 그룹은
"정리하지 않음"(건너뛰기)이 기본값이다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QGridLayout,
    QLabel,
    QMenu,
    QPushButton,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
)

from gui.common_dialogs import confirm_dialog, info_dialog, ProgressDialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS
from gui.thumbnail import ClickableThumbnail, load_thumbnail_qimage
from gui.trash_worker import TrashMoveWorker

THUMB_SIZE = 150
DEFAULT_THRESHOLD = 10


class _CurrentOnlyStack(QStackedWidget):
    """gui/organize_hub_screen.py::_CurrentOnlyStack와 같은 이유로 필요 — 기본
    QStackedWidget은 숨겨진 페이지도 sizeHint에 반영해서, empty_label만 보여줄
    때도 scroll_area(stretch=1)가 있던 자리만큼 빈 공간을 남긴다. 게다가
    setVisible()만으로 감추면(예전 방식) wordWrap 라벨이 그 남는 공간을 예측
    불가능하게 늘어나 먹어버리는 문제까지 있었다(2026-09-10, 사용자 리포트 —
    "카드형태 버튼이 세로로 늘어나는 현상", gui/duplicate_screen.py와 같은
    원인/수정). setCurrentWidget()으로 완전히 바꿔치기해야 둘 다 해결된다."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()

# 그룹 안에서 서로 다른 폴더를 뱃지 색으로 구분하기 위한 팔레트 — 테마 색만
# 재사용(새 색을 추가하지 않음). 그룹 하나에 폴더가 팔레트 크기보다 많으면
# 순환해서 재사용한다(흔치 않은 경우라 색이 겹쳐도 큰 문제 없음).
_FOLDER_BADGE_PALETTE = (COLORS["primary"], COLORS["warning"], COLORS["danger"], COLORS["success"])


def _folder_badge_colors(group: list) -> dict:
    """그룹 안 파일들의 부모 폴더별로 뱃지 색을 배정한다(같은 폴더는 같은 색).
    dict[Path, str]."""
    colors: dict = {}
    for info in group:
        folder = Path(info.path).parent
        if folder not in colors:
            colors[folder] = _FOLDER_BADGE_PALETTE[len(colors) % len(_FOLDER_BADGE_PALETTE)]
    return colors


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _similar_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 겹친 원 두 개로 "닮았다"는 의미. gui/duplicate_screen.py
    (완전 중복, 겹친 사각형)와 구분되게 원으로 다르게 그린다."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    painter.drawEllipse(r(2, 5, 14, 14))
    painter.drawEllipse(r(8, 5, 14, 14))
    painter.end()
    return pixmap


def _group_similarity_note(files: list) -> str:
    """그룹이 왜 묶였는지 사람이 읽을 문구 — 정확도를 직접 판단할 수 있게
    구체적인 근거(거리 값)를 보여준다."""
    hashed = [(f, int(f.perceptual_hash, 16)) for f in files if f.perceptual_hash]
    best = None
    for i in range(len(hashed)):
        for j in range(i + 1, len(hashed)):
            distance = bin(hashed[i][1] ^ hashed[j][1]).count("1")
            if best is None or distance < best:
                best = distance
    if best is None:
        return "파일명 패턴이 비슷해서 묶였어요 (예: a.jpg / a_1.jpg)"
    return f"이미지 유사도 거리 {best} (0에 가까울수록 거의 같은 사진)"


class _WrappingPhotoRow(QWidget):
    """사진 카드 하나 안에서 여러 장을 가로로 나열하다가, 폭이 모자라면
    자동으로 다음 줄로 넘어간다(2026-09-09, 사용자 리포트 — "5장 이상이면
    짤려 보임": 기존 QHBoxLayout은 줄바꿈이 없는데 가로 스크롤도 막아놔서
    넘치는 사진이 아예 안 보였다). gui/date_group_detail_screen.py의 그리드
    재배치와 같은 원리를 카드 하나 스코프로 축소해서 재사용."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setSpacing(18)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._cells: list[QWidget] = []
        self._cell_width = 0
        self._last_columns = -1

    def set_cells(self, cells: list[QWidget], cell_width: int) -> None:
        self._cells = cells
        self._cell_width = max(cell_width, 1)
        self._last_columns = -1
        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        if not self._cells:
            return
        available = self.width() or (self.parentWidget().width() if self.parentWidget() else 0)
        spacing = self._grid.spacing()
        columns = max(1, (available + spacing) // (self._cell_width + spacing))
        if columns == self._last_columns:
            return
        self._last_columns = columns
        for cell in self._cells:
            self._grid.removeWidget(cell)
        for idx, cell in enumerate(self._cells):
            self._grid.addWidget(cell, idx // columns, idx % columns)


class _SimilarPreloadWorker(QThread):
    """similar_groups() 계산(사진이 많으면 느릴 수 있음 — 퍼셉추얼 해시
    쌍 비교가 O(n^2)) + 카드에 쓸 썸네일 로딩을 한 번에 백그라운드에서
    처리한다. QImage는 스레드 세이프하지만 QPixmap은 아니라서(gui/thumbnail.py
    참고) 여기서는 QImage까지만 만들고, 실제 QPixmap 변환은 메인 스레드인
    카드 생성 시점에 한다."""

    progress = Signal(int, int)
    finished_batch = Signal(list, dict)  # groups, {path: QImage | None}

    def __init__(self, result, threshold: int, parent=None):
        super().__init__(parent)
        self._result = result
        self._threshold = threshold
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        groups = self._result.similar_groups(self._threshold)
        thumbs: dict = {}
        paths = [info.path for group in groups for info in group]
        total = len(paths)
        for idx, path in enumerate(paths, start=1):
            if self._cancel_requested:
                break
            thumbs[path] = load_thumbnail_qimage(path, THUMB_SIZE)
            self.progress.emit(idx, total)
        self.finished_batch.emit(groups, thumbs)


class _GroupEntry:
    """건너뛰기 전용 라디오는 없앴다(2026-09-09, 사용자 요청 — "1장 이상
    남기고 싶으면?") — 체크박스만 두고, 아무것도 체크 안 하거나 전부
    체크하면(지울 게 없으므로) 자동으로 건너뛰기와 같은 뜻이 된다."""

    __slots__ = ("card", "group", "checkboxes")

    def __init__(self, card, group, checkboxes):
        self.card = card
        self.group = group
        self.checkboxes = checkboxes


class SimilarScreen(QWidget):
    """검사 결과 화면(gui/result_screen.py)의 "유사 사진 보기" 버튼으로 들어오는
    화면. 같은 스캔 세션(gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    # 정리(휴지통 이동) 완료 후 휴지통 화면으로 이동 — 이번에 옮긴 FileInfo 목록을
    # 같이 넘긴다(gui/duplicate_screen.py::view_trash_requested와 같은 이유).
    view_trash_requested = Signal(list)
    # 파일 클릭/미리보기 -> 상세보기(FileInfo, 그 파일이 속한 그룹 — 상세
    # 화면에서 방향키로 같은 그룹의 다음/이전 사진을 넘나들 때 씀, 2026-09-08).
    file_selected = Signal(object, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None
        self._entries: list[_GroupEntry] = []
        self._thumb_cache: dict = {}
        self._worker: _SimilarPreloadWorker | None = None

        # 화면 전체를 쓰는 큰 창에서 카드가 창 끝까지 늘어나면 사진 줄 뒤로 텅 빈
        # 공간이 남아 허전해 보인다(gui/organize_hub_screen.py에서 고친 것과 같은
        # 문제) — 내용 폭을 한 번 고정(960px)하고 가운데 정렬한다. 그룹핑/정리
        # 로직은 전혀 안 건드리고 바깥 컨테이너만 바꾼 것.
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(960)
        # stretch factor 0인 위젯은 양옆 addStretch(1)에 밀려 sizeHint만큼만
        # 차지하고 절대 안 커진다 — setMaximumWidth는 상한만 정할 뿐, 실제로
        # 그 상한까지 채우는 힘은 Expanding 정책 + 양옆보다 훨씬 큰 stretch
        # factor가 있어야 생긴다(2026-09-08, 사용자 리포트 — "정리 화면이
        # 이상하게 좁다", gui/duplicate_screen.py와 같은 원인/수정).
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
        title_icon.setPixmap(_similar_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("유사 사진")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.group_chip = SummaryChip("유사 그룹", COLORS["warning"])
        self.file_chip = SummaryChip("사진", COLORS["warning"])
        chips_row.addWidget(self.group_chip)
        chips_row.addWidget(self.file_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "완전히 같지는 않지만 비슷해 보이는 사진들이에요 — 오탐일 수 있으니 썸네일을 직접 보고 판단해주세요. "
            "지우고 싶은 사진에 체크하세요(여러 장 가능) — 아무것도 체크하지 않으면 이 그룹은 그대로 둬요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel("유사한 사진이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        # 카드는 항상 컨테이너 폭에 맞춰지므로 가로 스크롤은 필요 없다
        # (gui/duplicate_screen.py와 같은 이유로 추가, 2026-09-08).
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll_area.setWidget(self._list_container)

        self.list_stack = _CurrentOnlyStack()
        self.list_stack.addWidget(self.empty_label)
        self.list_stack.addWidget(self.scroll_area)
        outer.addWidget(self.list_stack, stretch=1)

        # 처음엔 체크=남기기, 건너뛰기 판단은 "체크 안 한 파일이 옮겨짐"이었는데
        # (2026-09-09) 사진이 많은 그룹에서 지우고 싶은 몇 장만 빼고 나머지
        # 전부를 일일이 체크해야 해서 오히려 불편했다(2026-09-10, 사용자 리포트
        # — "선택 안 한게 많으니까 삭제할 수가 없음") — 체크=지우기로 뒤집어서
        # 지울 몇 장만 체크하면 되게 바꿨다. gui/duplicate_screen.py의 라디오
        # (남길 파일 하나 고르기)는 그룹 성격이 달라(정확 중복은 결국 하나만
        # 남기는 게 목적) 그대로 둔다.
        self.cleanup_btn = QPushButton("체크한 파일 임시 휴지통으로 이동")
        self.cleanup_btn.setObjectName("Danger")
        self.cleanup_btn.setEnabled(False)
        self.cleanup_btn.clicked.connect(self._on_cleanup_clicked)
        outer.addWidget(self.cleanup_btn)

        # 그룹핑 계산 + 썸네일 로딩 진행 중 보여줄 팝업(gui/common_dialogs.py 공용).
        self._progress_dialog = ProgressDialog(self)
        self._progress_dialog.cancel_requested.connect(self._on_preload_cancel_requested)

        # "정리 실행"으로 파일을 옮기는 동안 보여줄 별도 진행률 팝업 — 위 미리보기
        # 계산용(self._progress_dialog/self._worker)과 겹치지 않게 이름을 다르게
        # 둔다(gui/duplicate_screen.py와 같은 gui/trash_worker.py::TrashMoveWorker
        # 재사용).
        self.cleanup_progress_dialog = ProgressDialog(self)
        self.cleanup_progress_dialog.cancel_requested.connect(self._on_cleanup_cancel_requested)
        self._cleanup_worker: TrashMoveWorker | None = None
        self._pending_entry_refs: list[_GroupEntry] | None = None

    def set_result(self, result) -> None:
        """검사 결과를 받아 similar_groups()를 백그라운드로 계산하고 화면을
        새로 그린다."""
        self._result = result
        if self._worker is not None:
            return

        self._worker = _SimilarPreloadWorker(result, DEFAULT_THRESHOLD, self)
        self._worker.progress.connect(self._on_preload_progress)
        self._worker.finished_batch.connect(self._on_preload_finished)

        self._progress_dialog.start("비슷한 사진 찾는 중")
        self._worker.start()
        self._progress_dialog.exec()

    def has_pending(self) -> bool:
        """임시 휴지통에서 뒤로 나올 때 빈 화면을 거치지 않고 검사 결과로
        바로 보낼지 판단하는 데 쓰인다(gui/duplicate_screen.py와 같은 용도)."""
        return bool(self._entries)

    def _on_preload_progress(self, current: int, total: int):
        self._progress_dialog.update_progress(current, max(total, 1), "사진 비교 중")

    def _on_preload_cancel_requested(self):
        if self._worker is not None:
            self._worker.cancel()

    def _on_preload_finished(self, groups: list, thumbs: dict):
        self._progress_dialog.accept()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.wait()
        self._thumb_cache.update(thumbs)
        self._render_groups(groups)

    def _render_groups(self, groups: list) -> None:
        self._entries = []
        self.setUpdatesEnabled(False)
        try:
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            for row, group in enumerate(groups):
                card, checkboxes = self._build_group_card(row + 1, group)
                self._entries.append(_GroupEntry(card, group, checkboxes))
                self._list_layout.insertWidget(row, card)

            self._refresh_summary()
        finally:
            self.setUpdatesEnabled(True)

    def _refresh_summary(self) -> None:
        group_count = len(self._entries)
        file_count = sum(len(e.group) for e in self._entries)
        has_any = bool(self._entries)

        self.group_chip.set_value(group_count)
        self.file_chip.set_value(file_count)
        self.list_stack.setCurrentWidget(self.scroll_area if has_any else self.empty_label)
        self.cleanup_btn.setEnabled(has_any)

    def _build_group_card(self, idx: int, group: list) -> tuple[QFrame, list[QCheckBox]]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header = QLabel(f"유사 그룹 {idx} · {len(group)}개 파일")
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        note = QLabel(_group_similarity_note(group))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        layout.addWidget(note)

        # 사진마다 체크박스로 "지우기"를 고른다(2026-09-09, 사용자 요청 —
        # "1장 이상 남기고 싶으면?" 당시엔 체크=남기기였다가, 2026-09-10
        # 사용자 리포트로 체크=지우기로 뒤집었다 — 그룹 안 대부분은 남기고
        # 소수만 지우는 경우가 많아, 지울 몇 장만 체크하는 쪽이 더 적은
        # 클릭으로 끝난다). 라디오+별도 "건너뛰기" 대신, 아무것도 체크
        # 안 하거나(지울 게 없음) 전부 체크하면(남길 게 없음) 자동으로
        # 건너뛰기와 같은 뜻이 된다 — _on_cleanup_clicked 참고. 기본값은
        # 전부 체크 해제(오탐 가능성이 있어 완전 중복보다도 더 보수적으로
        # — 아무것도 안 건드리는 쪽이 기본).
        #
        # 사진을 가로로 나란히 놓아야 서로 다른 점이 눈에 더 잘 들어온다는
        # 피드백으로 세로 목록에서 바꿨다 — 사진도 더 키우고(THUMB_SIZE),
        # 세로 목록일 때는 사진 옆 여백에 폴더 경로를 그대로 적어 넣을 수
        # 있었지만 가로로 눕히면 그 자리가 없어져서, 대신 사진마다 작은
        # "폴더" 뱃지를 붙여 어떤 게 같은 폴더 사진인지 색으로 표시한다.
        # 사진이 많으면(5장+) 한 줄에 다 못 들어가 잘려 보이던 문제가 있어
        # (2026-09-09, 사용자 리포트) _WrappingPhotoRow로 자동 줄바꿈한다.
        #
        # 표 형태(체크옵션/구분/파일명/사유)로 통일해봤다가 되돌렸다
        # (2026-09-08, 사용자 판단 — "중복은 해시로 100% 같은 파일이라
        # 비교할 필요가 없지만, 유사는 오탐 가능성이 있는 추정이라 실제
        # 큰 썸네일로 비교해야 맞다").
        folder_colors = _folder_badge_colors(group)

        checkboxes: list[QCheckBox] = []
        cells: list[QWidget] = []
        for info in group:
            col = QVBoxLayout()
            col.setSpacing(6)
            col.setAlignment(Qt.AlignHCenter)

            pixmap = None
            image = self._thumb_cache.get(info.path)
            if image is not None:
                pixmap = QPixmap.fromImage(image)
            thumb = ClickableThumbnail(pixmap, info.filename, size=THUMB_SIZE)
            thumb.clicked.connect(lambda info=info, group=group: self.file_selected.emit(info, group))
            # 우클릭으로 미리보기/로컬 폴더 위치 열기 — gui/duplicate_screen.py
            # 표들과 같은 패턴(2026-09-09, 사용자 요청 — 카톡으로 받아 이름만
            # 바뀐 사진인지 직접 파일 크기/폴더를 확인해보고 싶다는 니즈).
            thumb.setContextMenuPolicy(Qt.CustomContextMenu)
            thumb.customContextMenuRequested.connect(
                lambda pos, info=info, group=group, w=thumb: self._on_thumb_context_menu(w, pos, info, group)
            )
            col.addWidget(thumb)

            check_row = QHBoxLayout()
            check_row.setAlignment(Qt.AlignHCenter)
            checkbox = QCheckBox("이 파일 지우기")
            checkbox.setToolTip("이 파일을 임시 휴지통으로 옮깁니다")
            checkbox.setStyleSheet("font-size: 11px;")
            checkboxes.append(checkbox)
            check_row.addWidget(checkbox)
            col.addLayout(check_row)

            folder = Path(info.path).parent
            badge_color = folder_colors[folder]
            # 폴더명 1단계만 보여주면(예: "08") 날짜별 정리 폴더처럼 상위
            # 폴더(연도)까지 알아야 뜻이 통하는 경우 헷갈려서, 뒤에서 2단계까지
            # 보여준다("2016/08"). 전체 경로는 툴팁으로.
            short_folder = "/".join(folder.parts[-2:]) if len(folder.parts) >= 2 else folder.name
            badge = QLabel(f"📁 {short_folder}")
            badge.setAlignment(Qt.AlignCenter)
            badge.setToolTip(str(folder))  # 뱃지엔 짧게, 전체 경로는 툴팁으로
            badge.setStyleSheet(
                f"background-color: {_hex_to_rgba(badge_color, 0.13)}; color: {badge_color}; "
                f"border: 1px solid {_hex_to_rgba(badge_color, 0.4)}; border-radius: 9px; "
                f"padding: 2px 8px; font-size: 10.5px; font-weight: 600;"
            )
            col.addWidget(badge, alignment=Qt.AlignHCenter)

            col_widget = QWidget()
            col_widget.setLayout(col)
            cells.append(col_widget)

        photo_grid = _WrappingPhotoRow()
        cell_width = max((cell.sizeHint().width() for cell in cells), default=THUMB_SIZE + 16)
        photo_grid.set_cells(cells, cell_width)
        layout.addWidget(photo_grid)

        return card, checkboxes

    def _on_thumb_context_menu(self, widget: QWidget, pos, info, group: list) -> None:
        menu = QMenu(self)
        preview_action = menu.addAction("미리보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is preview_action:
            self.file_selected.emit(info, group)
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _on_cleanup_clicked(self):
        # gui/duplicate_screen.py::_on_cleanup_clicked와 같은 방식 — 그룹마다
        # 임시휴지통 서브폴더 + 사유를 남긴다(utils/trash.py::create_trash_group).
        # entry_refs는 to_process와 인덱스가 1:1로 맞는 병렬 목록 — 워커가 끝난
        # 뒤 "이 카드를 지워도 되는지"를 판단하는 데 쓴다(gui/trash_worker.py).
        to_process: list[tuple[str, list, str]] = []
        entry_refs: list[_GroupEntry] = []

        for entry in self._entries:
            remove_infos = [info for info, cb in zip(entry.group, entry.checkboxes) if cb.isChecked()]
            keep_infos = [info for info, cb in zip(entry.group, entry.checkboxes) if not cb.isChecked()]
            # 아무것도 체크 안 함(remove_infos 없음) 또는 전부 체크(남길 게
            # 없음) 둘 다 "이 그룹은 건드리지 않음"과 같은 뜻이다 — 별도
            # "건너뛰기" 컨트롤 없이 체크 상태만으로 판단한다.
            if not keep_infos or not remove_infos:
                continue
            keep_info = keep_infos[0]
            extra = f" 외 {len(keep_infos) - 1}장 더" if len(keep_infos) > 1 else ""
            reason = (
                f"유사 사진 정리 — '{Path(keep_info.path).name}'{extra} 파일을 남기고 이 파일들이 이동됨 "
                f"({_group_similarity_note(entry.group)})"
            )
            to_process.append((keep_info.path, remove_infos, reason))
            entry_refs.append(entry)

        total_to_remove = sum(len(infos) for _, infos, _ in to_process)
        if not total_to_remove:
            info_dialog(self, "정리할 파일을 선택하지 않았어요.\n지울 파일을 먼저 체크해주세요.")
            return

        confirmed = confirm_dialog(
            self,
            f"선택한 {total_to_remove}개 파일을 임시 휴지통으로 옮길게요.\n\n"
            "완전히 삭제되는 게 아니라서 나중에 원래 위치로 복원할 수 있어요.",
            confirm_text="이동",
            cancel_text="취소",
        )
        if not confirmed:
            return

        self._pending_entry_refs = entry_refs
        self._cleanup_worker = TrashMoveWorker(to_process, self)
        self._cleanup_worker.progress.connect(self._on_cleanup_progress)
        self._cleanup_worker.finished_batch.connect(self._on_cleanup_finished)
        self.cleanup_progress_dialog.start("임시 휴지통으로 옮기는 중")
        self._cleanup_worker.start()
        self.cleanup_progress_dialog.exec()

    def _on_cleanup_progress(self, current: int, total: int, filename: str) -> None:
        self.cleanup_progress_dialog.update_progress(current, total, filename)

    def _on_cleanup_cancel_requested(self) -> None:
        if self._cleanup_worker is not None:
            self._cleanup_worker.cancel()

    def _on_cleanup_finished(self, moved: int, failed: list, moved_infos: list, completed_entry_indices: list) -> None:
        self.cleanup_progress_dialog.accept()
        worker = self._cleanup_worker
        self._cleanup_worker = None
        if worker is not None:
            worker.wait()

        if self._result is not None:
            for info in moved_infos:
                self._result.remove(info)

        if failed:
            info_dialog(
                self,
                f"{moved}개 파일을 임시 휴지통으로 옮겼습니다.\n"
                f"{len(failed)}개는 옮기지 못했습니다:\n" + "\n".join(failed),
            )
        else:
            info_dialog(self, f"{moved}개 파일을 임시 휴지통으로 옮겼습니다.\n확인해주세요.")

        # 취소로 아예 시도조차 안 된 카드는 다음에 다시 볼 수 있게 남긴다.
        entry_refs = self._pending_entry_refs or []
        self._pending_entry_refs = None
        for idx in completed_entry_indices:
            entry = entry_refs[idx]
            self._entries.remove(entry)
            entry.card.deleteLater()
        self._refresh_summary()

        if moved:
            self.view_trash_requested.emit(moved_infos)
