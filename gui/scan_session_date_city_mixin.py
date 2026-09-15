"""
gui/scan_session_date_city_mixin.py

gui/scan_session_window.py::ScanSessionWindow의 일부. 검사 결과 화면(정리
카드 포함, 2026-09-13에 옛 정리 허브를 합침)의 "날짜별 정리" / "도시별 정리"
카드 전환 + 두 화면이 함께 쓰는 그룹 상세(date_group_detail_screen) 로직.
둘 다 같은 그룹 상세 화면·시그니처(set_group_excluded(label, excluded_paths))를
공유해서 한 파일에 같이 뒀다.

ScanSessionWindow에 다중 상속으로만 섞이는 믹스인이라 self.xxx는
ScanSessionWindow.__init__이 준비한 속성이다. 단독으로 인스턴스화하지 않는다.
"""

from __future__ import annotations

from gui.common_dialogs import info_dialog as _info_dialog


class DateCityOrganizeMixin:
    def _open_date_organize(self):
        result = self.result_screen.result
        if not result or not result.files:
            _info_dialog(self, "정리할 사진이 없습니다.")
            return
        self.date_organize_screen.set_result(result)
        self.date_organize_screen.set_output_root(str(self._default_organize_output_dir() / "날짜별_정리"))
        self.stack.setCurrentWidget(self.date_organize_screen)

    def _back_from_date_organize(self):
        self.stack.setCurrentWidget(self.result_screen)

    def _open_date_group_detail(self, label: str, files: list):
        self._group_detail_return_screen = self.date_organize_screen
        excluded = self.date_organize_screen.group_excluded(label)
        self.date_group_detail_screen.set_group(label, files, excluded_paths=excluded)
        self.stack.setCurrentWidget(self.date_group_detail_screen)

    def _open_city_organize(self):
        result = self.result_screen.result
        if not result or not result.files:
            _info_dialog(self, "정리할 사진이 없습니다.")
            return
        self.city_organize_screen.set_result(result)
        self.city_organize_screen.set_output_root(str(self._default_organize_output_dir() / "도시별_정리"))
        self.stack.setCurrentWidget(self.city_organize_screen)

    def _back_from_city_organize(self):
        self.stack.setCurrentWidget(self.result_screen)

    def _open_city_group_detail(self, label: str, info, files: list):
        self._group_detail_return_screen = self.city_organize_screen
        excluded = self.city_organize_screen.group_excluded(label)
        self.date_group_detail_screen.set_group(label, files, excluded_paths=excluded, initial_file=info)
        self.stack.setCurrentWidget(self.date_group_detail_screen)

    def _on_group_detail_exclusion_changed(self, label: str, excluded: set):
        # _group_detail_return_screen은 항상 date_organize_screen 또는
        # city_organize_screen 중 하나이고, 둘 다 같은 시그니처의
        # set_group_excluded(label, excluded_paths)를 갖고 있다.
        self._group_detail_return_screen.set_group_excluded(label, excluded)
