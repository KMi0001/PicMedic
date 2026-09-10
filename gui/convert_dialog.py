"""
gui/convert_dialog.py

홈화면 "변환" 카드 진입점(2026-09-10, 사용자 요청) — 전체 검사(core/scanner.py::
scan_paths, 폴더 전체를 중복/손상 기준으로 훑는 무거운 배치 작업) 없이 사진
파일/폴더를 바로 골라서 gui/recovery_screen.py의 "형식 변환" 모드를 연다.

두 단계로 준비한다: (1) core/scanner.py::list_image_files로 폴더를 사진 파일
목록만 가볍게 펼치고(순회 자체도 사진이 많으면 잠깐 걸릴 수 있어 바쁨 표시),
(2) 각 파일을 core/analyzer.py::analyze_file()로 개별 분석한다 — 변환이 형식을
알아야 하므로(HEIC 지원 여부 등) 이 분석 자체는 건너뛸 수 없지만, gui/
scan_session_window.py처럼 폴더 전체의 중복/유사 묶음을 만드는 무거운 배치
스캔과는 다르다(gui/scan_session_window.py::_LightListWorker와 같은 원칙).
여러 장을 한 번에 골라도 된다 — gui/recovery_screen.py가 원래 배치 처리를
지원한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QStackedWidget, QVBoxLayout, QWidget

from core.analyzer import analyze_file
from core.converter import RecoveryMode
from core.scanner import list_image_files
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.recovery_result_screen import RecoveryResultScreen
from gui.recovery_screen import RecoveryScreen
from models.file_info import FileInfo, FileStatus


class _ConvertPrepWorker(QThread):
    """list_image_files(폴더 훑기) + analyze_file(파일마다 개별 분석) 두 단계를
    순서대로 백그라운드에서 돈다. 총 개수를 미리 모르는 첫 단계는 progress를
    쏘지 않고(호출부가 바쁨 표시로 보여줌), 두 번째 단계부터 (현재, 전체, 파일명)을 쏜다."""

    listing_started = Signal()
    progress = Signal(int, int, str)
    finished_batch = Signal(list)  # list[FileInfo]

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        self.listing_started.emit()
        scan_result = list_image_files(self._paths, should_cancel=lambda: self._cancel_requested)
        file_paths = [Path(f.path) for f in scan_result.files]

        result: list[FileInfo] = []
        total = len(file_paths)
        for idx, path in enumerate(file_paths, start=1):
            if self._cancel_requested:
                break
            try:
                info = analyze_file(path)
            except Exception as exc:  # PRD 23.4: 개별 파일 오류가 전체 작업을 막아선 안 된다
                info = FileInfo(
                    path=str(path),
                    filename=path.name,
                    extension=path.suffix.lower(),
                    status=FileStatus.UNKNOWN,
                    error_message=f"분석 중 예외 발생: {exc}",
                )
            result.append(info)
            self.progress.emit(idx, total, path.name)
        self.finished_batch.emit(result)


def run_convert(parent: QWidget, paths: list[str]) -> None:
    """paths(파일/폴더 혼합 가능)를 사진 파일로 펼치고 분석한 뒤, 검사 없이
    곧장 "형식 변환" 화면을 연다."""
    progress_dialog = ProgressDialog(parent)
    worker = _ConvertPrepWorker(paths, parent)

    def on_listing_started():
        # 폴더 순회는 파일마다 처리하는 게 아니라 전체 개수를 미리 몰라서
        # (gui/scan_session_window.py::_LightListWorker와 같은 이유) 퍼센트
        # 대신 바쁨(busy) 표시로 보여준다.
        progress_dialog.bar.setRange(0, 0)
        progress_dialog.status_label.setText("폴더를 훑어보는 중...")

    def on_progress(current: int, total: int, name: str):
        progress_dialog.bar.setRange(0, 100)
        progress_dialog.update_progress(current, total, name)

    def on_finished(infos: list[FileInfo]):
        progress_dialog.accept()
        progress_dialog.bar.setRange(0, 100)  # 다음 실행을 위해 바쁨 표시 원상복구
        worker.wait()
        if not infos:
            info_dialog(parent, "선택한 위치에서 사진 파일을 찾지 못했어요.")
            return
        _open_convert_screen(parent, infos)

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.listing_started.connect(on_listing_started)
    worker.progress.connect(on_progress)
    worker.finished_batch.connect(on_finished)

    progress_dialog.start("사진 분석 중")
    worker.start()
    progress_dialog.exec()


def _open_convert_screen(parent: QWidget, files: list[FileInfo]) -> None:
    """gui/home_screen.py::_open_trash와 같은 패턴 — 스캔 세션(gui/
    scan_session_window.py) 없이 화면 두 개(복구/변환 설정 -> 결과)만 담은
    작은 창을 띄운다."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic — 변환")
    dialog.setWindowModality(Qt.WindowModal)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)

    stack = QStackedWidget()
    recovery_screen = RecoveryScreen()
    result_screen = RecoveryResultScreen()
    stack.addWidget(recovery_screen)
    stack.addWidget(result_screen)
    layout.addWidget(stack)

    def on_recovery_finished(outcomes, output_dir):
        result_screen.set_outcomes(outcomes, output_dir, title="변환")
        stack.setCurrentWidget(result_screen)

    recovery_screen.set_files(files, preselected_mode=RecoveryMode.CONVERT)
    recovery_screen.back_requested.connect(dialog.reject)
    recovery_screen.recovery_finished.connect(on_recovery_finished)
    result_screen.done_requested.connect(dialog.accept)

    dialog.resize(720, 780)
    dialog.exec()
