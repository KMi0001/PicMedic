"""
gui/scan_session_detail_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 상세보기 / 복구 /
임시휴지통 전환 로직 — 어느 목록 화면(검사 결과, 중복, 유사, 카테고리 찾기)에서
열렸는지에 따라 뒤로가기 대상이 달라지는 세 화면을 묶었다.

ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라 self.xxx는
ScanSessionWindow.__init__이 준비한 속성이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from models.file_info import FileStatus
from utils import trash


class DetailRecoveryTrashMixin:
    def _open_detail(self, info, group=None, return_to=None):
        self._detail_return_screen = return_to or self.result_screen
        # 중복/유사 사진 화면에서는 "이게 정말 맞나" 확인하러 들어온 것이라
        # 복구/변환/화질 개선 같은 편집 액션은 감춘다(gui/detail_screen.py::
        # set_review_only 참고) — gui/date_group_detail_screen.py와 같은 원칙.
        self.detail_screen.set_review_only(
            return_to in (self.duplicate_screen, self.similar_screen, *self.category_finder_screens.values())
        )
        # group을 주면(중복/유사 화면의 표에서 열었을 때) 상세 화면에서
        # 방향키로 같은 그룹의 다음/이전 사진을 넘나들 수 있다(2026-09-08,
        # 사용자 요청).
        self.detail_screen.set_file(info, group=group)
        self.stack.setCurrentWidget(self.detail_screen)

    def _open_recovery(self, files, mode):
        self.recovery_screen.set_files(files, preselected_mode=mode)
        self.stack.setCurrentWidget(self.recovery_screen)

    def _open_trash(self, return_to=None, moved_infos: list | None = None):
        self._trash_return_screen = return_to or self.result_screen
        if moved_infos:
            # 임시휴지통이 이제 "옮긴 파일이 있던 폴더마다" 따로 생기므로
            # (utils/trash.py), 이번에 실제로 옮겨진 파일들이 어느 폴더에서
            # 왔는지로 보여줄 임시휴지통 목록을 계산한다.
            trash_dirs = sorted({trash.trash_dir_for(info.path) for info in moved_infos})
            self.trash_screen.set_trash_dirs(trash_dirs)
        self.trash_screen.refresh()
        self.stack.setCurrentWidget(self.trash_screen)

    def _back_from_trash(self):
        if self._trash_return_screen is self.similar_screen and self.similar_screen.has_pending():
            self.stack.setCurrentWidget(self.similar_screen)
        elif self.duplicate_screen.has_pending():
            self.stack.setCurrentWidget(self.duplicate_screen)
        else:
            # 더 처리할 그룹이 없어 정리 허브로 바로 돌아가는 경우 — 그동안
            # 중복/유사 정리로 빠진 파일들이 표/칩/카드 배지에 반영되게 새로고침한다.
            self._refresh_after_organize_action()
            self.stack.setCurrentWidget(self.organize_hub_screen)

    def _on_recovery_finished(self, outcomes, output_dir):
        if self.result_screen.result is not None:
            for outcome in outcomes:
                # 원래 '정상'이던 파일은 복구가 아니라 단순 변환이므로 상태를 바꾸지 않는다
                if outcome.success and outcome.original.status != FileStatus.NORMAL:
                    self.result_screen.result.mark_recovered(outcome.original)
            self.result_screen.refresh_current_result()

        self.recovery_result_screen.set_outcomes(outcomes, output_dir)
        self.stack.setCurrentWidget(self.recovery_result_screen)
