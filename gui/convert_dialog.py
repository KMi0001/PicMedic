"""
gui/convert_dialog.py

홈화면 "변환" 카드 진입점(2026-09-10, 사용자 요청) — 전체 검사(core/scanner.py::
scan_paths, 폴더 전체를 중복/손상 기준으로 훑는 무거운 배치 작업) 없이 사진
파일/폴더를 바로 골라서 gui/recovery_screen.py의 "형식 변환" 모드를 연다.

core/scanner.py::list_image_files로 폴더를 사진 파일 목록만 가볍게 펼치고
끝낸다 — core/analyzer.py::analyze_file()(파일 전체 SHA-256 해시 + 손상
판독까지 하는 무거운 개별 분석)은 일부러 건너뛴다. "형식 변환"(core/
converter.py::convert_to_format)은 실제 변환 시점에 파일을 다시 직접 열어서
처리할 뿐, 미리 분석해둔 해시/손상여부를 쓰지 않기 때문이다(2026-09-10,
사용자 리포트 — "2225장이라 분석이 오래 걸려" → analyze_file 자체를 생략하는
쪽으로 확정). 손상된 파일이 섞여 있어도 걸러내지 않고 그냥 시도하다가
실패하면 결과 화면에 실패로 뜬다 — 변환은 원본을 건드리지 않으니(원본 삭제
옵션을 켜지 않는 한) 안전하다.

폴더 안에 확장자가 여러 종류 섞여 있으면(_filter_by_extension) 어떤 확장자만
바꿀지 먼저 고르게 한다 — 그렇지 않으면 원치 않는 확장자까지 전부 변환
대상이 된다(2026-09-10, 사용자 요청 — "특정 확장자만 바꾸고 싶은데").

여러 장을 한 번에 골라도 된다 — gui/recovery_screen.py가 원래 배치 처리를
지원한다.
"""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.converter import RecoveryMode
from core.scanner import list_image_files
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.recovery_result_screen import RecoveryResultScreen
from gui.recovery_screen import RecoveryScreen
from gui.theme import COLORS
from models.file_info import FileInfo
from models.scan_result import ScanResult


class _ListImagesWorker(QThread):
    """core/scanner.py::list_image_files를 백그라운드에서 돈다 — 폴더 순회
    자체도 사진이 수만 장이면 잠깐 걸릴 수 있어(디스크 I/O) 메인 스레드를
    막지 않는다. 총 개수를 미리 모르므로(gui/scan_session_window.py::
    _LightListWorker와 같은 이유) 진행률은 바쁨(busy) 표시로 보여준다."""

    finished_listing = Signal(object)  # ScanResult

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = paths
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        result = list_image_files(self._paths, should_cancel=lambda: self._cancel_requested)
        self.finished_listing.emit(result)


def run_convert(parent: QWidget, paths: list[str]) -> None:
    """paths(파일/폴더 혼합 가능)를 사진 파일로 펼친 뒤, 검사도 개별 분석도
    없이 곧장 "형식 변환" 화면을 연다."""
    progress_dialog = ProgressDialog(parent)
    worker = _ListImagesWorker(paths, parent)

    def on_finished(result: ScanResult):
        progress_dialog.accept()
        worker.wait()
        files = list(result.files)
        if not files:
            info_dialog(parent, "선택한 위치에서 사진 파일을 찾지 못했어요.")
            return
        filtered = _filter_by_extension(parent, files)
        if filtered:
            _open_convert_screen(parent, filtered)

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.finished_listing.connect(on_finished)

    progress_dialog.start("사진 목록을 모으는 중")
    progress_dialog.bar.setRange(0, 0)
    progress_dialog.status_label.setText("폴더를 훑어보는 중...")
    worker.start()
    progress_dialog.exec()


def _filter_by_extension(parent: QWidget, files: list[FileInfo]) -> list[FileInfo] | None:
    """확장자가 한 종류뿐이면 그대로 files를 돌려준다(고를 게 없으므로 팝업
    생략). 두 종류 이상이면 확장자별 개수를 보여주는 체크박스 팝업을 띄워서
    고른 확장자만 걸러 돌려준다. 취소했거나 하나도 안 골랐으면 None."""
    counts = Counter(f.extension.lower() for f in files)
    if len(counts) <= 1:
        return files

    dialog = QDialog(parent)
    dialog.setWindowTitle("PicMedic")
    dialog.setWindowModality(Qt.WindowModal)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    label = QLabel("어떤 확장자를 바꿀까요?")
    label.setStyleSheet("font-weight: 700; font-size: 14px;")
    layout.addWidget(label)

    hint = QLabel("고른 확장자의 사진만 변환 대상이 돼요.")
    hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
    layout.addWidget(hint)

    checks: dict[str, QCheckBox] = {}
    for ext, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        label_text = ext if ext else "(확장자 없음)"
        check = QCheckBox(f"{label_text}  —  {count}장")
        check.setChecked(True)
        layout.addWidget(check)
        checks[ext] = check

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = QPushButton("취소")
    confirm_btn = QPushButton("변환하기")
    confirm_btn.setObjectName("Primary")
    confirm_btn.setDefault(True)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(confirm_btn)
    layout.addLayout(btn_row)

    cancel_btn.clicked.connect(dialog.reject)
    confirm_btn.clicked.connect(dialog.accept)

    if dialog.exec() != QDialog.Accepted:
        return None

    selected_exts = {ext for ext, check in checks.items() if check.isChecked()}
    filtered = [f for f in files if f.extension.lower() in selected_exts]
    if not filtered:
        info_dialog(parent, "선택한 확장자가 없어서 변환할 사진이 없어요.")
        return None
    return filtered


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
