"""
gui/scan_session_duplicates_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 정리 허브의 "중복 사진" /
"유사 사진" 카드 전환 로직. ScanSessionWindow에 다중 상속으로만 섞이는
믹스인이라 self.xxx는 ScanSessionWindow.__init__/OrganizeExecutionMixin이
준비한 속성이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from gui.common_dialogs import info_dialog as _info_dialog


class DuplicatesSimilarMixin:
    def _back_from_duplicates(self):
        # duplicate_screen이 "정리 실행"으로 이미 self.result_screen.result(같은
        # ScanResult 객체)에서 파일을 뺐어도(ScanResult.remove), 검사 결과 화면의
        # 표/칩은 따로 다시 그려주지 않으면 그대로 갱신 안 된 채 남는다 — 휴지통에
        # 옮긴 사진이 검사 결과 목록에 계속 보이던 문제.
        self._refresh_after_organize_action()
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _back_from_similar(self):
        self._refresh_after_organize_action()
        self.stack.setCurrentWidget(self.organize_hub_screen)

    def _open_duplicates(self):
        # 2026-09-10: 아직 스캔 전이면(정리 허브를 방금 열었을 때) 여기서
        # 전체 스캔부터 시작하고, 끝나면 아래 로직을 다시 실행한다
        # (_ensure_scanned_then 참고). 이미 스캔돼 있으면(다른 카드를 먼저
        # 눌렀던 경우 등) 바로 실행된다.
        def proceed():
            result = self.result_screen.result
            if not result or not result.duplicate_groups():
                # 처리할 중복이 아예 없으면 빈 화면을 보여줄 필요 없이 정리
                # 허브로 바로 돌아간다.
                _info_dialog(self, "중복된 파일이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            self.duplicate_screen.set_result(result)
            self.stack.setCurrentWidget(self.duplicate_screen)

        self._ensure_scanned_then(proceed)

    def _open_similar(self):
        def proceed():
            result = self.result_screen.result
            if not result or not result.files:
                _info_dialog(self, "정리할 사진이 없습니다.")
                self.stack.setCurrentWidget(self.organize_hub_screen)
                return
            # similar_groups() 계산 자체가 느릴 수 있어(퍼셉추얼 해시 쌍 비교)
            # 여기서 미리 확인하지 않고, SimilarScreen이 백그라운드로 계산하는
            # 동안 진행률 팝업을 보여준다 — 결과가 없으면 화면 자체가 빈
            # 상태를 보여준다.
            self.similar_screen.set_result(result)
            self.stack.setCurrentWidget(self.similar_screen)

        self._ensure_scanned_then(proceed)
