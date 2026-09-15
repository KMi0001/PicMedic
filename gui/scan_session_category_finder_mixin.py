"""
gui/scan_session_category_finder_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 검사 결과 화면(정리
카드 포함)의 카테고리 찾기 카드(동물친구들/음식 사진/스크린샷/야경/풍경)
전환 로직.

2026-09-13: 검사 결과 화면과 별도였던 "정리 허브" 화면을 없애고 하나로
합치면서, "정리 카드는 스캔 없이 곧장 허브로 랜딩하고 카드를 눌러야 그때
스캔한다"는 지연 스캔 경로가 통째로 사라졌다 — 이제 카드를 누를 수 있는
시점엔 항상 전체 스캔이 이미 끝나 있으므로, 예전에 있던 "가벼운 스캔"
폴백(core/scanner.py::list_image_files만 쓰는 별도 경로)이 필요 없어졌다.

ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라 self.xxx는
ScanSessionWindow.__init__이 준비한 속성이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from core.category_finder import CATEGORIES as CATEGORY_FINDER_DEFS


class CategoryFinderMixin:
    def _open_category_finder(self, category_id: str):
        # 검사 결과 화면이 진입 시점에 이미 카테고리 5개를 전부 백그라운드로
        # 계산해두므로, 그 결과가 준비돼 있으면 재계산 없이 곧장 보여준다 —
        # 워커·진행률 팝업 생략.
        screen = self.category_finder_screens[category_id]
        folder_name = CATEGORY_FINDER_DEFS[category_id].output_folder_name
        screen.set_output_root(str(self._default_organize_output_dir() / folder_name))

        matches = self.result_screen.category_matches(category_id)
        if matches is not None:
            screen.set_matches(matches)
        else:
            # 백그라운드 계산이 아직 안 끝났으면(스캔 직후 잠깐) 이 화면이
            # 직접 계산하도록 폴백한다.
            screen.set_result(self.result_screen.result)
        self.stack.setCurrentWidget(screen)

    def _back_from_category_finder(self):
        self.stack.setCurrentWidget(self.result_screen)
