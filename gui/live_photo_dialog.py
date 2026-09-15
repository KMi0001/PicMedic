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

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
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
        list_widget.addItem(QListWidgetItem(f"{m.image_path.name}  ↔  {m.mov_path.name}"))
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
