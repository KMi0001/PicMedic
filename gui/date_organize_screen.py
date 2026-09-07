"""
gui/date_organize_screen.py

Phase 2-2 "날짜별 분류" — PHASE2_사진정리_기획.md "2026-09-01 논의: 뷰어 우선
정리" 원칙 적용. 스캔 결과를 EXIF 촬영일(DateTimeOriginal) 기준으로 묶어
미리보기만 보여준다 — 그룹 계산 → 화면 표시까지만이고, 실제 파일 복사/이동은
사용자가 아래에서 방식(복사/이동)을 고르고 "정리하기"를 눌러야만 일어난다
(뷰어와 실행의 완전한 분리).

주의(문구 원칙): 이 화면 자체는 아직 아무 파일도 건드리지 않은 상태이므로
"정리됨"/"완료" 같은 표현을 쓰지 않는다 — "미리보기"/"이렇게 묶여요"처럼
실행 전임이 분명한 표현만 사용한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.common_dialogs import ProgressDialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS
from gui.thumbnail import load_thumbnail_qimage

THUMB_SIZE = 64
MAX_THUMBS_PER_CARD = 5
NO_DATE_LABEL = "날짜 정보 없음"


def _calendar_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 달력 모양 아웃라인. 다른 페이지 제목 아이콘(중복
    사진의 겹친 사각형, 휴지통의 통 모양)과 같은 스트로크 스타일로 맞춘다."""
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

    def r(x, y, w, h):
        return QRectF(x * scale, y * scale, w * scale, h * scale)

    def p(x, y):
        return QPointF(x * scale, y * scale)

    painter.drawRoundedRect(r(3, 5, 18, 16), 2 * scale, 2 * scale)
    painter.drawLine(p(3, 10), p(21, 10))
    painter.drawLine(p(8, 3), p(8, 7))
    painter.drawLine(p(16, 3), p(16, 7))
    painter.end()
    return pixmap


class _ThumbnailPreloadWorker(QThread):
    """그룹 카드에 쓸 썸네일을 미리 불러온다. 사진이 많으면(그룹마다 최대
    MAX_THUMBS_PER_CARD장씩) 디코딩에 잠깐 시간이 걸려서, 메인 스레드에서
    그대로 하면 화면이 멈춘 것처럼 보인다 — QImage는 스레드 세이프해서
    (QPixmap과 달리) 백그라운드에서 미리 만들어두고, 실제 QPixmap 변환만
    나중에 메인 스레드에서 한다(gui/thumbnail.py::load_thumbnail_qimage)."""

    progress = Signal(int, int)
    finished_batch = Signal(dict)  # {path: QImage | None}

    def __init__(self, paths: list[str], size: int, parent=None):
        super().__init__(parent)
        self._paths = paths
        self._size = size
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        result = {}
        total = len(self._paths)
        for idx, path in enumerate(self._paths, start=1):
            if self._cancel_requested:
                break
            result[path] = load_thumbnail_qimage(path, self._size)
            self.progress.emit(idx, total)
        self.finished_batch.emit(result)


class _ClickableCard(QFrame):
    """그룹 카드 하나 — 눌리면 clicked를 쏜다. gui/home_screen.py::_RecentRow와
    같은 패턴(카드 전체가 버튼처럼 동작, 어떤 그룹인지는 호출부가 이미 앎)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DateOrganizeScreen(QWidget):
    """검사 결과를 날짜별로 미리 묶어 보여주는 화면. 같은 검사 세션
    (gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    organize_requested = Signal(str)  # "copy" | "move" — "정리하기" 클릭 시점의 방식
    group_opened = Signal(str, list)  # 그룹 카드 클릭 — (라벨, FileInfo 목록)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None  # models.scan_result.ScanResult
        self._groups: list[tuple[str, list]] = []  # (라벨, FileInfo 목록)
        # 그룹 상세 화면(gui/date_group_detail_screen.py)에서 체크 해제한 사진들 —
        # label -> 제외된 파일 경로 집합. groups()가 "정리하기" 실행 대상을
        # 넘길 때 여기 있는 경로는 걸러낸다.
        self._group_exclusions: dict[str, set[str]] = {}
        self._output_root: str = ""
        self._thumb_cache: dict[str, object] = {}  # path -> QImage | None, 그룹 재계산에도 재사용
        self._thumb_worker: _ThumbnailPreloadWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_calendar_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("날짜별 정리")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)
        self.range_chip = SummaryChip("촬영 기간", COLORS["primary"])
        self.file_chip = SummaryChip("사진", COLORS["primary"])
        self.no_date_chip = SummaryChip("날짜없음", COLORS["muted"])
        chips_row.addWidget(self.range_chip)
        chips_row.addWidget(self.file_chip)
        chips_row.addWidget(self.no_date_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "미리보기예요 — 아직 아무 파일도 옮기지 않았어요. 촬영일(EXIF) 기준으로 이렇게 묶여요. "
            "아래에서 방식을 고르고 \"정리하기\"를 눌러야 실제로 복사/이동돼요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        granularity_row = QHBoxLayout()
        granularity_row.setSpacing(10)
        granularity_label = QLabel("묶는 단위")
        granularity_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        granularity_row.addWidget(granularity_label)
        granularity_buttons = QButtonGroup(self)
        self.month_radio = QRadioButton("월별")
        self.month_radio.setChecked(True)
        self.year_radio = QRadioButton("연도별")
        granularity_buttons.addButton(self.month_radio)
        granularity_buttons.addButton(self.year_radio)
        self.month_radio.toggled.connect(self._on_granularity_toggled)
        self.year_radio.toggled.connect(self._on_granularity_toggled)
        granularity_row.addWidget(self.month_radio)
        granularity_row.addWidget(self.year_radio)
        granularity_row.addStretch(1)
        outer.addLayout(granularity_row)

        self.empty_label = QLabel("정리할 사진이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch(1)
        self.scroll_area.setWidget(self._list_container)
        outer.addWidget(self.scroll_area, stretch=1)

        # --- 하단: 방식 선택 + 저장 위치 + 실행 ---
        mode_card = QFrame()
        mode_card.setObjectName("Card")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(18, 14, 18, 14)
        mode_layout.setSpacing(8)

        mode_header_row = QHBoxLayout()
        mode_header_row.setSpacing(8)
        mode_label = QLabel("정리 방식")
        mode_label.setStyleSheet("font-weight: 700;")
        mode_header_row.addWidget(mode_label)
        no_date_note = QLabel(f"\"{NO_DATE_LABEL}\" 사진들은 따로 \"{NO_DATE_LABEL}\" 폴더에 모아요.")
        no_date_note.setWordWrap(True)
        no_date_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        mode_header_row.addWidget(no_date_note, stretch=1)
        mode_layout.addLayout(mode_header_row)

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

        # 썸네일을 미리 불러오는 동안 보여줄 진행률 팝업(gui/common_dialogs.py 공용) —
        # "정리하기" 실행 진행률과는 별개(그건 gui/scan_session_window.py가 자체 팝업으로 처리).
        self._preload_progress = ProgressDialog(self)
        self._preload_progress.cancel_requested.connect(self._on_preload_cancel_requested)

    # --- 외부에서 호출 --------------------------------------------------

    def set_result(self, result) -> None:
        """검사 결과를 받아서 현재 "묶는 단위"로 그룹을 계산하고 다시 그린다.
        정리 허브를 오가며 같은 스캔 결과로 이 화면에 다시 들어올 때도 이
        메서드가 매번 불리므로, 정말 다른 결과(새 스캔/이어서 검사로 병합된
        결과)일 때만 그룹 상세에서 체크 해제해둔 제외 목록을 초기화한다."""
        if result is not self._result:
            self._group_exclusions = {}
        self._result = result
        self._load_groups()

    def set_output_root(self, path: str) -> None:
        self._output_root = path
        self.output_path_label.setText(path)

    def output_root(self) -> str:
        return self._output_root

    def groups(self) -> list[tuple[str, list]]:
        """현재 화면에 표시된 (라벨, FileInfo 목록)에서, 그룹 상세 화면에서 체크
        해제된 사진들을 뺀 뒤 반환한다 — "정리하기"를 실제로 실행할 호출부
        (gui/scan_session_window.py)가 core/date_organizer.py::organize_by_date()에
        그대로 넘길 수 있게."""
        if not self._group_exclusions:
            return self._groups
        result = []
        for label, files in self._groups:
            excluded = self._group_exclusions.get(label)
            if excluded:
                files = [f for f in files if f.path not in excluded]
            result.append((label, files))
        return result

    def group_excluded(self, label: str) -> set[str]:
        """label 그룹을 다시 열 때(gui/date_group_detail_screen.py) 이전에
        체크 해제해둔 경로를 그대로 복원하기 위함."""
        return set(self._group_exclusions.get(label, ()))

    def set_group_excluded(self, label: str, excluded_paths: set[str]) -> None:
        if excluded_paths:
            self._group_exclusions[label] = set(excluded_paths)
        else:
            self._group_exclusions.pop(label, None)
        # 그룹 상세에서 방금 체크 해제하고 돌아온 참일 수 있으니, 카드
        # 헤더의 "N장/N장" 표시도 바로 갱신한다.
        self._render_groups()

    def granularity(self) -> str:
        return "year" if self.year_radio.isChecked() else "month"

    # --- 그룹 계산 + 썸네일 미리 불러오기 --------------------------------

    def _on_granularity_toggled(self, checked: bool):
        if not checked:
            return  # QButtonGroup 라디오는 off->on 두 번 신호가 오므로 켜지는 쪽만 처리
        self._load_groups()

    def _load_groups(self):
        if self._result is None:
            self._groups = []
            self._render_groups()
            return

        self._groups = self._result.date_groups(self.granularity())

        needed_paths = [
            info.path
            for _, files in self._groups
            for info in files[:MAX_THUMBS_PER_CARD]
            if info.path not in self._thumb_cache
        ]

        if self._thumb_worker is not None:
            return  # 이미 로딩 중(예: 라디오를 빠르게 연타) — 새 요청은 무시

        if not needed_paths:
            self._render_groups()
            return

        self._thumb_worker = _ThumbnailPreloadWorker(needed_paths, THUMB_SIZE, self)
        self._thumb_worker.progress.connect(self._on_preload_progress)
        self._thumb_worker.finished_batch.connect(self._on_preload_finished)

        self._preload_progress.start("사진 불러오는 중")
        self._thumb_worker.start()
        self._preload_progress.exec()

    def _on_preload_progress(self, current: int, total: int):
        self._preload_progress.update_progress(current, total, "사진")

    def _on_preload_cancel_requested(self):
        if self._thumb_worker is not None:
            self._thumb_worker.cancel()

    def _on_preload_finished(self, thumbnails: dict):
        self._preload_progress.accept()
        worker = self._thumb_worker
        self._thumb_worker = None
        if worker is not None:
            worker.wait()
        self._thumb_cache.update(thumbnails)
        self._render_groups()

    # --- 렌더링 -----------------------------------------------------------

    def _render_groups(self) -> None:
        self.setUpdatesEnabled(False)
        try:
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            for row, (label, files) in enumerate(self._groups):
                card = self._build_group_card(label, files)
                self._list_layout.insertWidget(row, card)

            total_photos = sum(len(files) for _, files in self._groups)
            no_date_count = sum(len(files) for label, files in self._groups if label == NO_DATE_LABEL)
            dated_files = [f for label, files in self._groups if label != NO_DATE_LABEL for f in files]

            self.file_chip.set_value(total_photos)
            self.no_date_chip.set_value(no_date_count)
            self.range_chip.set_text(self._format_range(dated_files))

            has_any = bool(self._groups)
            self.empty_label.setVisible(not has_any)
            self.scroll_area.setVisible(has_any)
            self.organize_btn.setEnabled(has_any)
        finally:
            self.setUpdatesEnabled(True)

    def _format_range(self, dated_files: list) -> str:
        if not dated_files:
            return "-"
        dates = [f.captured_at for f in dated_files]
        earliest, latest = min(dates), max(dates)
        if self.granularity() == "year":
            if earliest.year == latest.year:
                return f"{earliest.year}"
            return f"{earliest.year} ~ {latest.year}"
        if (earliest.year, earliest.month) == (latest.year, latest.month):
            return f"{earliest.year}.{earliest.month:02d}"
        # "~" 앞뒤에 공백을 둬서 카드 폭에 안 들어갈 때 그 자리에서 두 줄로
        # 자연스럽게 줄바꿈되게 한다(SummaryChip.set_text의 word-wrap 참고) —
        # 절대 잘려 보이면 안 된다는 원칙.
        return f"{earliest.year}.{earliest.month:02d} ~ {latest.year}.{latest.month:02d}"

    def _build_group_card(self, label: str, files: list) -> QFrame:
        card = _ClickableCard()
        card.setObjectName("Card")
        card.setToolTip("눌러서 이 그룹의 사진을 확인합니다")
        card.clicked.connect(lambda label=label, files=files: self.group_opened.emit(label, files))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        is_no_date = label == NO_DATE_LABEL
        excluded = self._group_exclusions.get(label)
        if excluded:
            count_text = f"{len(files) - len(excluded)}장/{len(files)}장 (제외 {len(excluded)}장)"
        else:
            count_text = f"{len(files)}장"
        header = QLabel(f"{label} · {count_text}")
        header.setStyleSheet(
            f"font-weight: 700; color: {COLORS['text_secondary']};" if is_no_date else "font-weight: 700;"
        )
        # 카드 전체가 클릭 영역이라, 위에 얹힌 라벨들이 클릭을 가로채지 않고
        # 그대로 통과시켜서 밑에 있는 _ClickableCard.mousePressEvent가 받게 한다.
        header.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(header)

        strip = QHBoxLayout()
        strip.setSpacing(6)
        for info in files[:MAX_THUMBS_PER_CARD]:
            thumb = QLabel()
            thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setAttribute(Qt.WA_TransparentForMouseEvents)
            image = self._thumb_cache.get(info.path)
            if image is not None:
                thumb.setPixmap(QPixmap.fromImage(image))
            else:
                thumb.setStyleSheet(f"background-color: {COLORS['border']};")
            strip.addWidget(thumb)

        remaining = len(files) - MAX_THUMBS_PER_CARD
        if remaining > 0:
            more = QLabel(f"+{remaining}")
            more.setFixedSize(THUMB_SIZE, THUMB_SIZE)
            more.setAlignment(Qt.AlignCenter)
            more.setAttribute(Qt.WA_TransparentForMouseEvents)
            more.setStyleSheet(
                f"background-color: {COLORS['selection']}; color: {COLORS['primary']}; "
                f"font-weight: 700; border-radius: 4px;"
            )
            strip.addWidget(more)

        strip.addStretch(1)
        layout.addLayout(strip)

        return card

    def _on_change_output_clicked(self):
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self._output_root or "")
        if chosen:
            self.set_output_root(chosen)

    def _on_organize_clicked(self):
        mode = "move" if self.move_radio.isChecked() else "copy"
        self.organize_requested.emit(mode)
