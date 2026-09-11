"""
gui/scan_session_organize_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 날짜별/도시별/고양이 찾기
"정리하기" 실행 공통 로직(이동 확인, 워커 시작, 진행률, 완료/실패 처리)을 모았다
— 세 화면 모두 같은 _OrganizeWorker와 organize_progress_dialog를 공유한다.

ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라 self.xxx는 전부
ScanSessionWindow.__init__에서 준비된 속성(organize_progress_dialog,
_organize_worker, result_screen 등)이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from core.date_organizer import organize_by_city, organize_by_date, organize_cat_finder_results
from gui.common_dialogs import confirm_dialog as _confirm_dialog, info_dialog_with_folder as _info_dialog_with_folder
from gui.common_dialogs import info_dialog as _info_dialog
from gui.scan_session_workers import _OrganizeWorker


class OrganizeExecutionMixin:
    def _back_from_organize_hub(self):
        self.stack.setCurrentWidget(self.result_screen)

    def _refresh_after_organize_action(self):
        """중복/유사 정리, 휴지통 복원 등으로 검사 결과가 바뀐 뒤 정리 허브로
        돌아갈 때 표/칩(검사 결과 화면)과 카드 배지(정리 허브)를 같이
        새로고침한다 — 둘 중 하나만 갱신하면 반대쪽에 옛 개수가 남는다."""
        self.result_screen.refresh_current_result()
        self.organize_hub_screen.set_result(self.result_screen.result)

    def _confirm_move_if_needed(self, mode: str) -> bool:
        if mode != "move":
            return True
        return _confirm_dialog(
            self,
            "이동을 선택하셨어요.<br><br>"
            "원본 파일이 새 폴더로 옮겨지고 원래 위치에는 남지 않아요.<br>"
            "계속할까요?",
            confirm_text="이동 시작",
            cancel_text="취소",
        )

    def _start_organize_worker(self, run_fn, mode: str, output_root: str):
        self._organize_worker = _OrganizeWorker(run_fn, mode, output_root, self)
        self._organize_worker.progress.connect(self._on_organize_progress)
        self._organize_worker.finished_batch.connect(self._on_organize_finished)
        self._organize_worker.failed.connect(self._on_organize_failed)

        title = "이동하는 중" if mode == "move" else "복사하는 중"
        self.organize_progress_dialog.start(title)
        self._organize_worker.start()
        self.organize_progress_dialog.exec()

    def _on_date_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        groups = self.date_organize_screen.groups()
        output_root = self.date_organize_screen.output_root()
        granularity = self.date_organize_screen.granularity()
        run_fn = lambda progress_callback, should_cancel: organize_by_date(
            groups, mode, output_root, granularity=granularity,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_city_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        groups = self.city_organize_screen.groups()
        output_root = self.city_organize_screen.output_root()
        run_fn = lambda progress_callback, should_cancel: organize_by_city(
            groups, mode, output_root,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_cat_finder_organize_requested(self, mode: str):
        if self._organize_worker is not None:
            return
        if not self._confirm_move_if_needed(mode):
            return

        files = self.cat_finder_screen.matched_files()
        output_root = self.cat_finder_screen.output_root()
        run_fn = lambda progress_callback, should_cancel: organize_cat_finder_results(
            files, mode, output_root,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )
        # 2026-09-10부터 organize_hub_screen은 어느 경로로 오든(가벼운 고양이
        # 찾기든, 다른 카드로 이미 스캔했든) 항상 채워져 있으므로 완료 후
        # 기본값(그리로 돌아감)을 그대로 쓴다.
        self._start_organize_worker(run_fn, mode, output_root)

    def _on_organize_progress(self, current: int, total: int, filename: str):
        self.organize_progress_dialog.update_progress(current, total, filename)

    def _on_organize_cancel_requested(self):
        if self._organize_worker is not None:
            self._organize_worker.cancel()

    def _on_organize_failed(self, message: str):
        """정리(날짜별/도시별/고양이) 실행이 예상 못한 오류로 끝난 경우 —
        모달 진행 팝업을 먼저 닫아야 앱이 멈춘 것처럼 보이지 않는다.
        core/date_organizer.py는 파일을 옮기기 전에 실패하면 원본을 그대로
        두므로, 여기서는 안내만 하고 허브로 돌려보낸다."""
        self.organize_progress_dialog.accept()
        worker = self._organize_worker
        self._organize_worker = None
        if worker is not None:
            worker.wait()
        _info_dialog(self, f"정리 중 예상하지 못한 오류가 발생했습니다.\n\n{message}")
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _on_organize_finished(self, outcomes):
        self.organize_progress_dialog.accept()
        worker = self._organize_worker
        self._organize_worker = None
        if worker is not None:
            worker.wait()

        # "이미 있어서 건너뜀"(core/date_organizer.py::_already_organized)은 실제로
        # 옮기거나 복사한 게 아니므로 newly_done과 분리해서 센다 — 이동 모드에서
        # 특히 중요: 건너뛴 파일은 원본을 일부러 그대로 뒀으니(안전한 선택),
        # 검사 결과 목록에서도 빼면 안 된다(빼면 아직 안 옮겨진 파일이 사라진
        # 유령 항목이 됨).
        newly_done = [o for o in outcomes if o.success and not o.skipped]
        skipped = [o for o in outcomes if o.skipped]
        failed = [o for o in outcomes if not o.success]

        if worker is not None and worker.mode == "move" and self.result_screen.result is not None:
            for outcome in newly_done:
                self.result_screen.result.remove(outcome.original)
            self._refresh_after_organize_action()

        output_root = worker.output_root if worker is not None else ""

        lines = [f"{len(newly_done)}개 정리했습니다."]
        if skipped:
            lines.append(f"{len(skipped)}개는 이미 있어서 건너뛰었습니다.")
        if failed:
            lines.append(f"{len(failed)}개는 실패했습니다:")
            lines.extend(f"{o.original.filename} ({o.error_message})" for o in failed[:5])

        _info_dialog_with_folder(self, "\n".join(lines), output_root)

        self.stack.setCurrentWidget(self.organize_hub_screen)
