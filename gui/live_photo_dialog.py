"""
gui/live_photo_dialog.py

홈화면 "라이브 포토" 카드 진입점 — gui/convert_dialog.py와 같은 패턴(전체
검사 없이 사진 파일/폴더를 바로 골라서 여는 독립 다이얼로그).

core/live_photo_finder.py로 사진<->MOV 짝을 찾은 뒤, 찾은 목록에서
"동영상으로 내보내기"(MOV를 사진 이름 기준으로 그대로 복사) 또는 "이
사진들만 정리하기"(확인된 쌍만 새 폴더로 모으기) 중 골라 실행한다. 두 실행
다 gui/scan_session_workers.py::_OrganizeWorker(진행률 있는 배치 실행 공용
워커)를 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.live_photo_finder import (
    LivePhotoMatch,
    export_live_photo_videos,
    find_live_photo_matches,
    organize_live_photo_pairs,
)
from gui.common_dialogs import ProgressDialog, info_dialog, info_dialog_with_folder
from gui.image_viewer import ImageViewer
from gui.scan_session_workers import _OrganizeWorker
from gui.theme import COLORS


class _FindLivePhotoWorker(QThread):
    progress = Signal(int, int, str)
    finished_matches = Signal(list)  # list[LivePhotoMatch]
    failed = Signal(str)

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        # gui/scan_session_workers.py::_OrganizeWorker.run과 같은 이유 — 예외가
        # 새어나가면 진행률 팝업이 안 닫힌다.
        try:
            matches = find_live_photo_matches(
                self._paths,
                progress_callback=lambda cur, total, name: self.progress.emit(cur, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_matches.emit(matches)


def run_live_photo_finder(parent: QWidget, paths: list[str]) -> None:
    """paths(파일/폴더 혼합 가능) 아래에서 라이브 포토(사진+MOV) 짝을 찾는다."""
    progress_dialog = ProgressDialog(parent)
    worker = _FindLivePhotoWorker(paths, parent)

    def on_finished(matches: list[LivePhotoMatch]):
        progress_dialog.accept()
        worker.wait()
        if not matches:
            info_dialog(
                parent,
                "라이브 포토를 찾지 못했어요.\n"
                "사진과 짝 동영상(.MOV)이 검사 범위 안에 함께 있어야 찾을 수 있어요.",
            )
            return
        _open_result_dialog(parent, paths, matches)

    def on_failed(message: str):
        progress_dialog.accept()
        worker.wait()
        info_dialog(parent, f"라이브 포토를 찾는 중 예상하지 못한 오류가 발생했어요.\n\n{message}")

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(progress_dialog.update_progress)
    worker.finished_matches.connect(on_finished)
    worker.failed.connect(on_failed)

    progress_dialog.start("라이브 포토 찾는 중")
    progress_dialog.status_label.setText("사진과 동영상을 대조하는 중...")
    worker.start()
    progress_dialog.exec()


def _default_output_root(paths: list[str]) -> Path:
    """gui/scan_session_window.py::_default_organize_output_dir과 같은 기준 —
    맨 처음 고른 경로가 폴더면 그 폴더, 파일이면 그 파일의 부모 폴더."""
    origin = Path(paths[0]) if paths else Path.cwd()
    return origin if origin.is_dir() else origin.parent


def _build_match_row(m: LivePhotoMatch) -> QWidget:
    """목록 한 줄 — 파일명 줄 아래에 로컬 경로를 작은 글씨로 보여준다
    (2026-09-17, 사용자 요청 — "목록에 로컬 경로 보여주고"). 경로를 말줄임
    없이 그대로 보여주려고(PicMedic 전체 원칙 — 절대 자르지 않기) 한 줄
    QListWidgetItem 텍스트 대신 QLabel 두 개짜리 위젯으로 교체했다.

    사진과 MOV가 서로 다른 폴더에서 매칭될 수 있다(UUID로만 짝을 찾지
    폴더는 안 따짐 — find_live_photo_matches 독스트링 참고, 예: 사진은 날짜별
    폴더로 정리했지만 동영상은 안 옮긴 경우). 두 경로가 같으면 한 줄로
    충분하지만, 다르면 "이 둘이 진짜 같은 폴더에 있다"고 착각하지 않도록
    각자 경로를 구분해서 두 줄로 보여준다."""
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.setSpacing(2)

    title = QLabel(f"{m.image_path.name}  ↔  {m.mov_path.name}")
    title.setStyleSheet("font-size: 12.5px;")
    layout.addWidget(title)

    path_style = f"color: {COLORS['text_secondary']}; font-size: 11px;"
    if m.image_path.parent == m.mov_path.parent:
        path_label = QLabel(str(m.image_path.parent))
        path_label.setStyleSheet(path_style)
        layout.addWidget(path_label)
    else:
        image_path_label = QLabel(f"사진: {m.image_path.parent}")
        image_path_label.setStyleSheet(path_style)
        layout.addWidget(image_path_label)
        mov_path_label = QLabel(f"동영상: {m.mov_path.parent}")
        mov_path_label.setStyleSheet(path_style)
        layout.addWidget(mov_path_label)

    return row


def _on_match_context_menu(parent: QWidget, list_widget: QListWidget, pos) -> None:
    item = list_widget.itemAt(pos)
    if item is None:
        return
    match: LivePhotoMatch = item.data(Qt.UserRole)
    same_folder = match.image_path.parent == match.mov_path.parent

    menu = QMenu(list_widget)
    preview_action = menu.addAction("미리보기")
    if same_folder:
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        open_image_folder_action = open_mov_folder_action = None
    else:
        open_folder_action = None
        open_image_folder_action = menu.addAction("사진 폴더 열기")
        open_mov_folder_action = menu.addAction("동영상 폴더 열기")
    chosen = menu.exec(list_widget.mapToGlobal(pos))
    if chosen is preview_action:
        _open_live_photo_preview(parent, match)
    elif chosen is open_folder_action or chosen is open_image_folder_action:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(match.image_path.parent)))
    elif chosen is open_mov_folder_action:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(match.mov_path.parent)))


def _open_live_photo_preview(parent: QWidget, match: LivePhotoMatch) -> None:
    """사진(정지 이미지) 쪽만 미리보기로 보여준다 — 짝이 맞는지 눈으로
    확인하는 용도라, 동영상까지 재생할 필요는 없다고 판단."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(match.image_path.name)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.resize(560, 560)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)

    viewer = ImageViewer(overlay_controls=True)
    viewer.set_image_path(str(match.image_path))
    layout.addWidget(viewer, stretch=1)

    path_label = QLabel(str(match.image_path))
    path_label.setWordWrap(True)
    path_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    layout.addWidget(path_label)

    dialog.exec()


def _open_result_dialog(parent: QWidget, origin_paths: list[str], matches: list[LivePhotoMatch]) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic — 라이브 포토")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.resize(520, 480)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    header = QLabel(f"라이브 포토 {len(matches)}개를 찾았어요")
    header.setStyleSheet("font-weight: 700; font-size: 16px;")
    layout.addWidget(header)

    hint = QLabel(
        "사진과 짝 동영상이 같은 식별자를 공유하는 걸 확인해서 찾은 목록이에요 — "
        "100% 정확하지는 않을 수 있어요."
    )
    hint.setWordWrap(True)
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px;")
    layout.addWidget(hint)

    list_widget = QListWidget()
    for m in matches:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, m)
        row = _build_match_row(m)
        item.setSizeHint(row.sizeHint())
        list_widget.addItem(item)
        list_widget.setItemWidget(item, row)
    list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
    list_widget.customContextMenuRequested.connect(lambda pos: _on_match_context_menu(dialog, list_widget, pos))
    layout.addWidget(list_widget)

    output_root = _default_output_root(origin_paths)

    btn_row = QHBoxLayout()
    export_btn = QPushButton("동영상으로 내보내기")
    organize_btn = QPushButton("이 사진들만 정리하기")
    organize_btn.setObjectName("Primary")
    btn_row.addWidget(export_btn)
    btn_row.addWidget(organize_btn)
    layout.addLayout(btn_row)

    close_btn = QPushButton("닫기")
    close_btn.clicked.connect(dialog.reject)
    layout.addWidget(close_btn)

    export_btn.clicked.connect(lambda: _pick_and_export(dialog, matches, output_root))
    organize_btn.clicked.connect(lambda: _pick_and_organize(dialog, matches, output_root))

    dialog.exec()


def _pick_output_dir(parent: QWidget, default_parent: Path) -> Path | None:
    """저장 위치를 사용자가 직접 고르게 한다(2026-09-15, 사용자 피드백 — 그냥
    알아서 폴더를 만들지 말고 위치를 고르게 해달라) — default_parent에서
    시작하되, 다른 폴더를 골라도 되고 다이얼로그 안의 "새 폴더" 만들기도
    그대로 쓸 수 있다."""
    start_dir = default_parent if default_parent.is_dir() else Path.home()
    chosen = QFileDialog.getExistingDirectory(parent, "저장할 폴더 선택", str(start_dir))
    if not chosen:
        return None
    return Path(chosen)


def _pick_and_export(parent: QWidget, matches: list[LivePhotoMatch], output_root: Path) -> None:
    output_dir = _pick_output_dir(parent, output_root)
    if output_dir is None:
        return
    _run_batch(
        parent,
        lambda progress_callback, should_cancel: export_live_photo_videos(
            matches, output_dir, progress_callback=progress_callback, should_cancel=should_cancel
        ),
        str(output_dir),
        "동영상 내보내는 중",
    )


def _pick_and_organize(parent: QWidget, matches: list[LivePhotoMatch], output_root: Path) -> None:
    output_dir = _pick_output_dir(parent, output_root)
    if output_dir is None:
        return
    _run_batch(
        parent,
        lambda progress_callback, should_cancel: organize_live_photo_pairs(
            matches, output_dir, mode="copy", progress_callback=progress_callback, should_cancel=should_cancel
        ),
        str(output_dir),
        "정리하는 중",
    )


def _run_batch(parent: QWidget, run_fn, output_dir: str, title: str) -> None:
    progress_dialog = ProgressDialog(parent)
    worker = _OrganizeWorker(run_fn, "copy", output_dir, parent)

    def on_finished(outcomes):
        progress_dialog.accept()
        worker.wait()
        success = sum(1 for o in outcomes if o.success)
        fail = sum(1 for o in outcomes if not o.success)
        message = f"{success}개 완료했어요."
        if fail:
            message += f"\n{fail}개는 실패했어요(다른 프로그램에서 쓰는 중이거나 저장 공간 부족 등)."
        info_dialog_with_folder(parent, message, output_dir)

    def on_failed(message: str):
        progress_dialog.accept()
        worker.wait()
        info_dialog(parent, f"예상하지 못한 오류가 발생했어요.\n\n{message}")

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(progress_dialog.update_progress)
    worker.finished_batch.connect(on_finished)
    worker.failed.connect(on_failed)

    progress_dialog.start(title)
    worker.start()
    progress_dialog.exec()
