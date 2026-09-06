"""
gui/quality_diagnosis_dialog.py

"사진 진단"(core/quality_diagnosis.py) 실행 흐름 — 화질 개선/얼굴 복원/
디블러/디노이즈 중 어느 걸 눌러야 할지 사용자가 감으로 고르지 않게, 먼저
사진을 분석해서 추천해준다. 다른 AI 기능들과 같은 모달 ProgressDialog로
진행하는 동안 다른 동작을 못 하게 막는다(2026-09-07, 사용자 요청 — 원래는
버튼 텍스트만 바꾸는 가벼운 방식이었는데, "항상 진행 중 표시"라는 앱 전체
원칙에 맞춰 통일했다).

배치(여러 장 한꺼번에 진단)는 없다 — 사용자가 "한 개의 파일만"이라고 명시.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import quality_diagnosis
from gui.common_dialogs import info_dialog, ProgressDialog
from gui.theme import COLORS

_ACTION_RUNNERS = {}  # 지연 등록 — 아래 _get_action_runners() 참고(순환 import 방지)


def _get_action_runners():
    """실행 함수들을 지연 import한다 — gui/detail_screen.py도 이 파일을 import하는데,
    각 *_dialog.py는 무거운 core 지연 import를 갖고 있어 모듈 최상단에서 전부
    끌어오면 불필요하게 느려진다(다른 AI 기능 다이얼로그들과 같은 원칙)."""
    if not _ACTION_RUNNERS:
        from gui.deblur_dialog import run_deblur
        from gui.denoise_dialog import run_denoise
        from gui.face_restore_dialog import run_face_restoration
        from gui.quality_enhance_dialog import run_quality_enhancement

        _ACTION_RUNNERS.update(
            {
                "디블러": lambda parent, path, w, h: run_deblur(parent, path, w, h),
                "디노이즈": lambda parent, path, w, h: run_denoise(parent, path, w, h),
                "얼굴 복원": lambda parent, path, w, h: run_face_restoration(parent, path),
                "화질 개선": lambda parent, path, w, h: run_quality_enhancement(parent, path, w, h),
            }
        )
    return _ACTION_RUNNERS


class _DiagnosisWorker(QThread):
    progress = Signal(int, int, str)
    succeeded = Signal(object)  # PhotoDiagnosis
    failed = Signal(str)

    def __init__(self, path: str, width: int | None, height: int | None, parent=None):
        super().__init__(parent)
        self._path = path
        self._width = width
        self._height = height
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            result = quality_diagnosis.diagnose_photo(
                self._path,
                self._width,
                self._height,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except quality_diagnosis.DiagnosisCancelled:
            return  # 취소는 에러가 아니므로 조용히 끝낸다
        except Exception as exc:  # noqa: BLE001 - 백그라운드 스레드 예외를 신호로 넘기기 위함
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class _DiagnosisResultDialog(QDialog):
    def __init__(self, result: quality_diagnosis.PhotoDiagnosis, path: str, width, height, parent=None):
        super().__init__(parent)
        self._path = path
        self._width = width
        self._height = height
        self._action = result.recommended_action

        self.setWindowTitle("PicMedic")
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("사진 진단 결과")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        if result.category:
            category_label = QLabel(f"카테고리: {result.category}")
            category_label.setStyleSheet(f"color: {COLORS['primary']}; font-weight: 600;")
            layout.addWidget(category_label)

        issue_lines = list(result.quality_issues)
        if result.faces:
            issue_lines.append(f"얼굴 {len(result.faces)}개 발견")
        if result.low_resolution:
            issue_lines.append("저해상도")
        issues_label = QLabel(", ".join(issue_lines) if issue_lines else "발견된 특징이 없어요.")
        issues_label.setWordWrap(True)
        issues_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(issues_label)

        reason_label = QLabel(result.recommended_reason)
        reason_label.setWordWrap(True)
        reason_label.setFixedWidth(320)
        reason_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(reason_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("닫기")
        btn_row.addWidget(close_btn)
        if self._action:
            run_btn = QPushButton(f"{self._action} 실행")
            run_btn.setObjectName("Primary")
            run_btn.setDefault(True)
            run_btn.clicked.connect(self._on_run_clicked)
            btn_row.addWidget(run_btn)
        layout.addLayout(btn_row)

        close_btn.clicked.connect(self.reject)

    def _on_run_clicked(self):
        self.accept()
        runner = _get_action_runners().get(self._action)
        if runner:
            runner(self.parent(), self._path, self._width, self._height)


def run_quality_diagnosis(
    parent: QWidget,
    path: str,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """path 사진을 진단한다 — 다른 AI 기능들과 같은 모달 ProgressDialog로
    분석 중임을 보여주고 다른 동작을 막는다."""
    progress_dialog = ProgressDialog(parent)
    worker = _DiagnosisWorker(path, width, height, parent)

    def on_progress(step: int, total: int, label: str):
        progress_dialog.update_progress(step, total, label)

    def on_succeeded(result: quality_diagnosis.PhotoDiagnosis):
        progress_dialog.accept()
        dialog = _DiagnosisResultDialog(result, path, width, height, parent)
        dialog.exec()

    def on_failed(message: str):
        progress_dialog.accept()
        info_dialog(parent, f"진단에 실패했습니다:\n{message}")

    def on_finished():
        if progress_dialog.isVisible():
            progress_dialog.accept()

    progress_dialog.cancel_requested.connect(worker.cancel)
    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_succeeded)
    worker.failed.connect(on_failed)
    worker.finished.connect(on_finished)

    progress_dialog.start("사진 진단 중")
    worker.start()
    progress_dialog.exec()
