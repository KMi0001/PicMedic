"""
gui/trash_screen.py

Phase 2 "사진 정리" — utils/trash.py::TRASH_DIR(임시 휴지통)에 옮겨진 파일을
"적용 후 빠른 검수" 화면으로 보여준다. 정리 실행 1회(= 그룹 서브폴더 1개,
utils/trash.py::create_trash_group)마다 카드 하나로 묶어서, "남긴 파일"과
"이동된 파일"들을 썸네일로 나란히 놓고 훑어볼 수 있게 하고, 잘못 옮겨진
파일은 그 자리에서 바로 "복원" 버튼으로 되돌릴 수 있다(선택 후 별도 버튼을
누르는 방식이 아니라 파일마다 즉시 실행 — 검수 흐름을 빠르게 하기 위함).
그룹 정보가 없는(평평하게 옮겨진) 옛 파일은 별도 카드로 모아서 보여준다.
gui/duplicate_screen.py에서 파일을 휴지통으로 옮긴 직후 이 화면으로 넘어온다.

실사용 중 발견된 버그: 휴지통에 파일이 수백 개 쌓이면(정리 실행을 몇 번만
해도 쉽게 도달) __init__이 곧바로 refresh()를 부르면서 파일마다
load_thumbnail()(동기 디코딩)을 다 돌려서, gui/scan_session_window.py::
ScanSessionWindow를 새로 만들 때마다(스캔을 새로 할 때마다!) 몇 초~몇십 초씩
메인 스레드가 멈췄다(실측: 850여 개에서 25초, "다시 검사"가 응답 없음처럼
보이던 원인). 두 가지로 고쳤다:
1. __init__에서 refresh()를 미리 부르지 않는다 — 실제로 화면을 열 때만
   (gui/scan_session_window.py::_open_trash) 부른다. 스캔 세션을 새로 만들
   때마다 휴지통 화면까지 미리 채울 필요가 없다.
2. refresh() 자체도 썸네일 디코딩을 백그라운드 스레드(_ThumbnailLoadWorker)로
   돌리고, 이미 불러온 썸네일은 self._thumb_cache에 남겨서(파일 삭제/복원으로
   refresh()가 반복 호출돼도) 다시 디코딩하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QDesktopServices, QImage
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
)

from gui.common_dialogs import info_dialog
from gui.result_screen import SummaryChip
from gui.theme import COLORS
from gui.thumbnail import load_thumbnail_qimage
from utils import trash
from utils.file_utils import format_file_size

_THUMB_SIZE = 56


class _ThumbnailLoadWorker(QThread):
    """paths 중 아직 캐시에 없는 파일만 백그라운드에서 QImage로 미리 불러온다
    (QImage는 스레드 세이프, QPixmap 변환은 메인 스레드에서 — gui/thumbnail.py
    참고). 한 장씩 thumbnail_ready로 돌려줘서, 다 끝나길 기다리지 않고 로드되는
    대로 화면에 바로 반영할 수 있게 한다."""

    thumbnail_ready = Signal(str, object)  # path str, QImage | None

    def __init__(self, paths: list[Path], size: int, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.size = size
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        for path in self.paths:
            if self._cancel_requested:
                break
            image = load_thumbnail_qimage(str(path), self.size) if path.exists() else None
            self.thumbnail_ready.emit(str(path), image)


def _trash_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 휴지통 모양 아웃라인. 다른 페이지 제목 아이콘과 같은
    스트로크 스타일(검사 결과의 돋보기, 복구의 화살표 등)."""
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
        from PySide6.QtCore import QPointF

        return QPointF(x * scale, y * scale)

    painter.drawLine(p(4, 7), p(20, 7))
    painter.drawLine(p(9, 4), p(15, 4))
    painter.drawRoundedRect(r(6, 7, 12, 14), 1.5 * scale, 1.5 * scale)
    painter.drawLine(p(10, 11), p(10, 17))
    painter.drawLine(p(14, 11), p(14, 17))

    painter.end()
    return pixmap


class TrashScreen(QWidget):
    """utils/trash.py의 임시 휴지통 내용을 보여주는 화면. 같은 스캔 세션 안에서만
    쓰인다(gui/scan_session_window.py)."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumb_cache: dict[str, "QImage | None"] = {}
        self._pending_labels: dict[str, list[QLabel]] = {}
        self._worker: _ThumbnailLoadWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setAlignment(Qt.AlignTop)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_trash_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("임시 휴지통")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        self.count_chip = SummaryChip("보관된 파일", COLORS["muted"])
        chips_row = QHBoxLayout()
        chips_row.addWidget(self.count_chip)
        chips_row.addStretch(1)
        outer.addLayout(chips_row)

        hint = QLabel(
            "완전히 삭제된 게 아니라 이 폴더로 옮겨진 것뿐이에요. "
            "그룹마다 남긴 파일과 이동된 파일을 나란히 보여드리니, 잘못 옮겨진 게 있으면 "
            "그 파일의 \"복원\"을 바로 눌러주세요. 필요 없으면 폴더를 열어서 직접 정리해주세요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.empty_label = QLabel("임시 휴지통이 비어 있습니다.")
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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        open_folder_btn = QPushButton("임시 휴지통 폴더 열기")
        open_folder_btn.clicked.connect(self._open_folder)
        btn_row.addWidget(open_folder_btn)
        outer.addLayout(btn_row)

        # 실제로 화면을 열 때만 채운다(gui/scan_session_window.py::_open_trash가
        # 호출) — 여기서 미리 부르면 스캔 세션을 새로 만들 때마다(스캔을 새로
        # 할 때마다!) 휴지통 파일이 많을 때 몇 초~몇십 초씩 멈춰 보인다.

    def refresh(self) -> None:
        """utils/trash.py의 실제 폴더 내용을 다시 읽어와 그룹별 카드로 갱신한다.
        썸네일은 캐시에 있으면 즉시, 없으면 자리만 잡아두고 백그라운드에서
        불러와 도착하는 대로 채운다(파일이 수백 개여도 카드 자체는 바로 뜸)."""
        files = trash.list_trash()
        self.count_chip.set_value(len(files))

        if self._worker is not None:
            # 이전 로딩이 아직 안 끝났으면 취소만 하고 손을 뗀다 — 곧 스스로
            # 멈추고(run() 안 취소 체크) 자기 자신을 정리한다(QThread를 실행
            # 중에 강제로 없애면 크래시 나므로).
            self._worker.cancel()
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker = None

        self._pending_labels = {}

        self.setUpdatesEnabled(False)
        try:
            while self._list_layout.count() > 1:
                item = self._list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            groups: dict[Path, list[Path]] = {}
            flat: list[Path] = []
            for path in files:
                if path.parent == trash.trash_dir():
                    flat.append(path)
                else:
                    groups.setdefault(path.parent, []).append(path)

            row = 0
            # 그룹 폴더명이 타임스탬프로 시작해서, 이름 내림차순 = 최근 정리 먼저
            for group_dir in sorted(groups, reverse=True):
                card = self._build_group_card(group_dir, sorted(groups[group_dir], key=lambda p: p.name))
                self._list_layout.insertWidget(row, card)
                row += 1

            if flat:
                card = self._build_flat_card(sorted(flat, key=lambda p: p.name))
                self._list_layout.insertWidget(row, card)
                row += 1

            has_any = bool(files)
            self.empty_label.setVisible(not has_any)
            self.scroll_area.setVisible(has_any)
        finally:
            self.setUpdatesEnabled(True)

        missing = [p for p in files if str(p) not in self._thumb_cache]
        if missing:
            self._worker = _ThumbnailLoadWorker(missing, _THUMB_SIZE, self)
            self._worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._worker.start()

    def _on_thumbnail_ready(self, path_str: str, image) -> None:
        self._thumb_cache[path_str] = image
        labels = self._pending_labels.get(path_str)
        if not labels:
            return  # 이미 다른 refresh()로 화면이 바뀌었거나, 이 파일이 더는 안 보임
        pixmap = QPixmap.fromImage(image) if image is not None else None
        for label in labels:
            if pixmap is not None:
                label.setPixmap(pixmap)
                label.setStyleSheet("")
            else:
                label.setText("?")

    def _build_group_card(self, group_dir: Path, moved_files: list[Path]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        reason = trash.group_reason_summary(moved_files[0]) if moved_files else None
        header = QLabel(reason or "정리 그룹")
        header.setWordWrap(True)
        header.setStyleSheet("font-weight: 700;")
        layout.addWidget(header)

        kept_path = trash.group_kept_path(moved_files[0]) if moved_files else None
        if kept_path:
            layout.addLayout(self._build_file_row(Path(kept_path), kept=True))

        for path in moved_files:
            layout.addLayout(self._build_file_row(path, kept=False))

        return card

    def _build_flat_card(self, files: list[Path]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        header = QLabel("그룹 정보 없음 (이 기능이 생기기 전에 옮겨진 파일)")
        header.setWordWrap(True)
        header.setStyleSheet(f"font-weight: 700; color: {COLORS['text_secondary']};")
        layout.addWidget(header)

        for path in files:
            layout.addLayout(self._build_file_row(path, kept=False))

        return card

    def _build_file_row(self, path: Path, *, kept: bool) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        thumb.setAlignment(Qt.AlignCenter)
        path_str = str(path)
        if path_str in self._thumb_cache:
            cached = self._thumb_cache[path_str]
            if cached is not None:
                thumb.setPixmap(QPixmap.fromImage(cached))
            else:
                thumb.setText("?")
                thumb.setStyleSheet(f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};")
        elif path.exists():
            # 아직 캐시에 없으면 자리만 잡아두고, _on_thumbnail_ready가 도착하는
            # 대로 채운다 — refresh()가 이 파일을 백그라운드 로딩 대상에 넣었음.
            thumb.setText("···")
            thumb.setStyleSheet(f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};")
            self._pending_labels.setdefault(path_str, []).append(thumb)
        else:
            thumb.setText("?")
            thumb.setStyleSheet(f"color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border']};")
        row.addWidget(thumb)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        name_label = QLabel(path.name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-weight: 600;" if kept else "")
        info_col.addWidget(name_label)

        if kept:
            badge = QLabel("유지됨 · 원래 위치에 그대로 있어요")
            badge.setStyleSheet(f"color: {COLORS['primary']}; font-size: 11px;")
        else:
            size = format_file_size(path.stat().st_size) if path.exists() else "-"
            badge = QLabel(f"이동됨 · {size}")
            badge.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        info_col.addWidget(badge)
        row.addLayout(info_col, stretch=1)

        if not kept:
            restore_btn = QPushButton("복원")
            restore_btn.clicked.connect(lambda checked=False, p=path: self._on_restore_one(p))
            row.addWidget(restore_btn)

        return row

    def _on_restore_one(self, path: Path) -> None:
        try:
            trash.restore_from_trash(path)
        except (ValueError, OSError) as exc:
            info_dialog(self, f"복원하지 못했습니다: {path.name} ({exc})")
            return
        self.refresh()

    def _open_folder(self):
        trash.trash_dir().mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(trash.trash_dir())))
