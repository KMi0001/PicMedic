"""
gui/detail_screen.py

PRD 19장 "Screen 04 — File Detail" 구현.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QGridLayout,
    QSizePolicy,
    QSplitter,
)

from core.converter import RecoveryMode
from gui.image_viewer import ImageViewer
from gui.theme import COLORS, STATUS_COLORS
from models.file_info import FileInfo, FileStatus
from utils.file_utils import format_file_size


class DetailScreen(QWidget):
    back_requested = Signal()
    recover_requested = Signal(list, object)  # [FileInfo], RecoveryMode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_info: FileInfo | None = None
        # 중복/유사 사진 화면에서 "미리보기"로 열렸을 때는 편집 액션(복구/
        # 변환/화질 개선)을 감춘다 — set_review_only() 참고.
        self._review_only = False
        # 같은 그룹(중복/유사 그룹 등) 안의 다른 사진들 — 방향키로 다음/이전
        # 사진으로 넘나들 때 쓴다(2026-09-08, 사용자 요청). set_file()이
        # group 없이(또는 파일 하나뿐인 그룹으로) 불리면 방향키는 그냥
        # 무시된다.
        self._group: list[FileInfo] = []
        self.setFocusPolicy(Qt.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(16)

        back_btn = QPushButton("\u2190 목록으로")
        back_btn.clicked.connect(self.back_requested.emit)
        outer.addWidget(back_btn, alignment=Qt.AlignLeft)

        # 화면 전체를 쓰는 레이아웃 — 미리보기는 창을 넓힐수록 같이 커지고, 정보
        # 패널은 폭을 고정 범위(300~420px)로 둬서 글자 줄바꿈이 요동치지 않게 한다
        # (experiments/fullframe_layout_prototype에서 검증한 구조 그대로).
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- 왼쪽: 미리보기 ---
        preview_card = QFrame()
        preview_card.setObjectName("Card")
        preview_layout = QVBoxLayout(preview_card)
        # 검사결과 목록 인라인 미리보기(gui/result_screen.py)와 같은 스타일로
        # 통일 — 회전/맞추기 버튼을 별도 줄 대신 사진 위에 반투명하게 얹는다
        # (2026-09-08, 사용자 요청 — "미리보기/뷰어는 다 검사결과 목록 미리보기처럼").
        self.preview_viewer = ImageViewer(
            placeholder_text="미리보기를 생성할 수 없습니다.", overlay_controls=True
        )
        self.preview_viewer.setMinimumSize(320, 320)
        self.preview_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(self.preview_viewer)
        splitter.addWidget(preview_card)

        # --- 오른쪽: 정보 + 액션 ---
        info_card = QFrame()
        info_card.setObjectName("Card")
        info_card.setMinimumWidth(300)
        info_card.setMaximumWidth(420)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(24, 24, 24, 24)
        info_layout.setSpacing(12)

        self.filename_label = QLabel()
        self.filename_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        info_layout.addWidget(self.filename_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.grid = grid
        self._grid_row = 0
        info_layout.addLayout(grid)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: 600;")
        info_layout.addWidget(self.warning_label)

        self.recovery_note_label = QLabel()
        self.recovery_note_label.setWordWrap(True)
        info_layout.addWidget(self.recovery_note_label)

        info_layout.addStretch(1)

        # 정보 패널이 고정 폭(300~420px)이라 버튼 3개를 가로로 나란히 두면 좁을 때
        # 줄바꿈이 들쭉날쭉해진다 — 세로로 쌓아서 패널 폭에 상관없이 안정적으로 맞춘다.
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)
        self.restore_btn = QPushButton("실제 형식으로 복구")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        btn_col.addWidget(self.restore_btn)
        self.convert_btn = QPushButton("확장자 변환")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.clicked.connect(self._on_convert_clicked)
        btn_col.addWidget(self.convert_btn)
        info_layout.addLayout(btn_col)

        splitter.addWidget(info_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        outer.addWidget(splitter, stretch=1)

    # --- 외부에서 호출 --------------------------------------------------

    def set_review_only(self, review_only: bool) -> None:
        """중복/유사 사진 화면에서 사진을 클릭해 "이게 정말 맞나" 확인만 하러
        들어왔을 때 True로 준다 — gui/date_group_detail_screen.py와 같은
        원칙: 정리 대상을 확인하는 화면에 복구/변환/화질 개선 같은 편집
        액션이 같이 있으면 오히려 헷갈린다(실사용 피드백). set_file() 호출
        전후 아무 때나 불러도 되고, 다음 set_file()부터 반영된다."""
        self._review_only = review_only

    def set_file(self, info: FileInfo, group: list[FileInfo] | None = None):
        """group을 주면(같은 중복/유사 그룹 등) 방향키(←/→)로 그 안의
        다음/이전 사진으로 넘나들 수 있다(2026-09-08, 사용자 요청) — 생략하면
        (또는 파일이 하나뿐이면) 방향키는 그냥 무시된다."""
        self.current_info = info
        self._group = group or []

        if len(self._group) > 1 and info in self._group:
            position = self._group.index(info) + 1
            self.filename_label.setText(f"{info.filename}  ({position}/{len(self._group)})")
        else:
            self.filename_label.setText(info.filename)

        self._clear_grid()
        self._add_row("파일 확장자", info.extension or "-")
        self._add_row("실제 형식", info.detected_format or "알 수 없음")
        self._add_row("파일 크기", format_file_size(info.file_size))
        if info.width and info.height:
            self._add_row("해상도", f"{info.width} × {info.height}")
        else:
            self._add_row("해상도", "-")
        status_color = STATUS_COLORS.get(info.status.value, COLORS["text"])
        self._add_row("상태", info.status.value.replace("_", " "), color=status_color)

        if info.is_mismatched:
            self.warning_label.setText("\u26a0 파일 확장자와 실제 이미지 형식이 일치하지 않습니다.")
            self.warning_label.show()
        elif info.status == FileStatus.CORRUPTED:
            self.warning_label.setText("\u26a0 이미지를 정상적으로 읽을 수 없습니다. 복구가 어려울 수 있습니다.")
            self.warning_label.show()
        elif info.status == FileStatus.PARTIAL_CORRUPTION:
            self.warning_label.setText("\u26a0 파일 일부가 손상되었습니다. 일부만 복구될 수 있습니다.")
            self.warning_label.show()
        else:
            self.warning_label.hide()

        recoverable = info.status in (FileStatus.MISMATCH, FileStatus.PARTIAL_CORRUPTION)
        # "복구"는 문제가 있는 파일에만 의미가 있으므로 그런 파일에서만 보여준다.
        # (review_only면 어떤 상태든 액션 자체를 감춘다 — set_review_only() 참고.)
        self.restore_btn.setVisible(recoverable and not self._review_only)
        self.restore_btn.setEnabled(recoverable and bool(info.detected_format))
        # "변환"은 복구와 무관하게, 디코딩만 된다면(readable) 정상 파일도 다른 형식으로
        # 바꿀 수 있어야 한다 (예: 정상 PNG를 웹 업로드용 WEBP로).
        self.convert_btn.setVisible(not self._review_only)
        self.convert_btn.setEnabled(info.readable)
        if self._review_only:
            self.recovery_note_label.setText("")
        elif recoverable:
            self.recovery_note_label.setText(
                "높은 확률로 복구할 수 있습니다."
                if info.status == FileStatus.MISMATCH
                else "일부 데이터가 손상되어 결과가 완전하지 않을 수 있습니다."
            )
        elif info.status == FileStatus.NORMAL:
            self.recovery_note_label.setText("다른 파일 형식으로 변환할 수 있습니다.")
        else:
            self.recovery_note_label.setText("")

        self.restore_btn.setText(
            f"{info.detected_format or '원본'} 형식으로 복구" if info.detected_format else "확장자 복구"
        )

        self._load_preview(info)
        self.setFocus()  # 클릭 없이 바로 방향키가 먹도록

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Left, Qt.Key_Right) and len(self._group) > 1 and self.current_info in self._group:
            delta = -1 if event.key() == Qt.Key_Left else 1
            idx = self._group.index(self.current_info)
            next_info = self._group[(idx + delta) % len(self._group)]
            self.set_file(next_info, group=self._group)
            event.accept()
            return
        super().keyPressEvent(event)

    # --- 내부 로직 -----------------------------------------------------

    def _clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._grid_row = 0

    def _add_row(self, label: str, value: str, color: str | None = None):
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {COLORS['text_secondary']};")
        value_widget = QLabel(value)
        if color:
            value_widget.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.grid.addWidget(label_widget, self._grid_row, 0)
        self.grid.addWidget(value_widget, self._grid_row, 1)
        self._grid_row += 1

    def _load_preview(self, info: FileInfo):
        self.preview_viewer.set_image_path(info.path)

    def _on_restore_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.RESTORE_EXTENSION)

    def _on_convert_clicked(self):
        if self.current_info:
            self.recover_requested.emit([self.current_info], RecoveryMode.CONVERT)
