"""
gui/scan_session_duplicates_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 검사 결과 화면(정리
카드 포함, 2026-09-13에 옛 정리 허브를 합침)의 "중복 사진" / "유사 사진"
카드 전환 로직. ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라
self.xxx는 ScanSessionWindow.__init__/OrganizeExecutionMixin이 준비한
속성이다. 단독으로 인스턴스화하지 않는다.
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
        self.stack.setCurrentWidget(self.result_screen)

    def _back_from_similar(self):
        self._refresh_after_organize_action()
        self.stack.setCurrentWidget(self.result_screen)

    def _open_duplicates(self):
        # 2026-09-13: 검사 결과 화면(정리 카드 포함)에 들어와 있다는 건 이미
        # 전체 스캔이 끝났다는 뜻이라(예전엔 "정리" 카드가 스캔 없이 곧장
        # 허브로 랜딩해서 여기서 스캔을 미뤄야 했음), result가 항상 채워져 있다.
        result = self.result_screen.result
        if not result or not result.duplicate_groups():
            _info_dialog(self, "중복된 파일이 없습니다.")
            return
        self.duplicate_screen.set_result(result)
        self.stack.setCurrentWidget(self.duplicate_screen)

    def _open_similar(self):
        result = self.result_screen.result
        if not result or not result.files:
            _info_dialog(self, "정리할 사진이 없습니다.")
            return
        # similar_groups() 계산 자체가 느릴 수 있어(퍼셉추얼 해시 쌍 비교)
        # 여기서 미리 확인하지 않고, SimilarScreen이 백그라운드로 계산하는
        # 동안 진행률 팝업을 보여준다 — 결과가 없으면 화면 자체가 빈
        # 상태를 보여준다.
        self.similar_screen.set_result(result)
        self.stack.setCurrentWidget(self.similar_screen)
