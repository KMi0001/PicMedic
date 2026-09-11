"""
gui/scan_session_cat_finder_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 정리 허브의 "고양이 찾기"
카드 전환 로직 — 다른 정리 카드(중복/유사/날짜별/도시별)와 달리 전체 진단 스캔과
무관하게 자기만의 가벼운 경로(core/scanner.py::list_image_files, 손상 검사·해시
생략)를 쓸 수 있어서 별도로 뺐다.

ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라 self.xxx는
ScanSessionWindow.__init__이 준비한 속성이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from gui.common_dialogs import info_dialog as _info_dialog
from gui.scan_session_workers import _LightListWorker


class CatFinderMixin:
    def _start_light_cat_finder_scan(self, paths: list[str]):
        """"정리 > 고양이 찾기" 빠른 경로 — core/scanner.py의 무거운 진단
        스캔(core/analyzer.py::analyze_file, 파일마다 SHA-256 전체 해시 +
        이미지 디코딩)을 건너뛰고 파일 목록만 가볍게 모은 뒤 곧장 고양이
        찾기로 간다. 정리 허브가 이미 보통 크기로 떠 있는 상태에서 카드를
        눌러 시작하므로(2026-09-10) 창 크기는 건드리지 않는다 — "결과 화면
        이후로는 창 크기를 다시 건드리지 않는다" 원칙(gui/scan_session_window.py
        참고)."""
        self._light_scan_worker = _LightListWorker(paths, self)
        self._light_scan_worker.finished_listing.connect(self._on_light_scan_finished)
        self._light_scan_worker.failed.connect(self._on_light_scan_failed)
        self.light_scan_progress_dialog.start("사진 목록을 모으는 중")
        # 총 개수를 미리 알 수 없어(진단처럼 파일마다 처리하는 게 아니라 폴더
        # 순회 자체) 퍼센트 대신 바쁨(busy) 표시로 보여준다.
        self.light_scan_progress_dialog.bar.setRange(0, 0)
        self.light_scan_progress_dialog.status_label.setText("폴더를 훑어보는 중...")
        self._light_scan_worker.start()
        self.light_scan_progress_dialog.exec()

    def _on_light_scan_cancel_requested(self):
        if self._light_scan_worker is not None:
            self._light_scan_worker.cancel()

    def _on_light_scan_failed(self, message: str):
        """"정리 > 고양이 찾기" 빠른 목록 수집이 실패한 경우 — _on_light_scan_finished와
        같은 뒷정리(모달 닫기, 바 범위 원복, 워커 정리)를 하고 허브로 돌려보낸다."""
        self.light_scan_progress_dialog.accept()
        self.light_scan_progress_dialog.bar.setRange(0, 100)
        worker = self._light_scan_worker
        self._light_scan_worker = None
        if worker is not None:
            worker.wait()
        _info_dialog(self, f"사진 목록을 모으는 중 예상하지 못한 오류가 발생했습니다.\n\n{message}")
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _on_light_scan_finished(self, result):
        self.light_scan_progress_dialog.accept()
        self.light_scan_progress_dialog.bar.setRange(0, 100)  # organize_progress_dialog와 인스턴스가 달라 공유 걱정은 없지만, 다음 실행을 위해 원상복구
        worker = self._light_scan_worker
        self._light_scan_worker = None
        if worker is not None:
            worker.wait()

        if result.total == 0:
            _info_dialog(self, "이미지 파일이 없습니다.")
            self.stack.setCurrentWidget(self.organize_hub_screen)
            return

        self.cat_finder_screen.set_output_root(str(self._default_organize_output_dir() / "고양이_사진"))
        self.cat_finder_screen.set_result(result)
        self.stack.setCurrentWidget(self.cat_finder_screen)

    def _open_cat_finder(self):
        # 고양이 찾기는 중복/유사/날짜별/도시별의 전체 스캔과 무관하다 — 이미
        # 그 스캔이 끝나 있으면(다른 카드를 먼저 눌렀던 경우) 재스캔 없이
        # 그 결과를 그대로 쓰고, 아직 스캔 전이면 자기만의 가벼운 경로
        # (_start_light_cat_finder_scan, 손상 검사·해시 생략)로 곧장 간다.
        result = self.result_screen.result
        if result is not None and result.files:
            self.cat_finder_screen.set_output_root(str(self._default_organize_output_dir() / "고양이_사진"))
            self.cat_finder_screen.set_result(result)
            self.stack.setCurrentWidget(self.cat_finder_screen)
            return
        self._start_light_cat_finder_scan(self._organize_paths)

    def _back_from_cat_finder(self):
        self.stack.setCurrentWidget(self.organize_hub_screen)
