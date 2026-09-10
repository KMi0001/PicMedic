"""
gui/city_organize_screen.py

Phase 2 "도시별 정리" — PHASE2_사진정리_기획.md "위치 시각화" + "뷰어 우선"
원칙 적용. gui/city_map_view.py 지도를 확대/이동하면 그 범위 안에 GPS가
찍힌 사진만 아래 목록에 보여주고, 목록에서 사진을 고르면
gui/date_group_detail_screen.py(뷰어 + 하단 썸네일 목록, 체크박스로 그룹에서
제외 가능)를 그대로 재사용해 자세히 볼 수 있다. gui/date_organize_screen.py와
같은 원칙으로 "정리하기"(복사/이동)도 지원한다 — 미리보기(지도 훑어보기)와
실행이 분리돼 있다.

목록에서 사진을 클릭하면 그 사진이 속한 "도시 그룹" 전체(현재 지도에 보이는
범위가 아니라)를 그룹 상세 화면에서 보여준다 — 체크 해제(제외)가 실제
"정리하기" 대상과 정확히 대응되게 하기 위함(지도 범위는 줌/팬마다 바뀌어서
그 자체를 그룹으로 삼으면 제외 목록이 무엇을 가리키는지 애매해진다).

위치 정보 없는 사진은 지도에 찍을 좌표가 없어 이 화면에는 안 보이지만,
"정리하기"를 실행하면 core/date_organizer.py::organize_by_city()가 별도
폴더("위치없음")로 모아준다.
experiments/city_organize_prototype에서 지도/줌 부분을 먼저 검증함.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.date_organizer import NO_CITY_LABEL
from gui.city_map_view import CityMapView
from gui.theme import COLORS
from models.file_info import FileInfo


def _pin_icon_pixmap(color: str, size: int = 26) -> QPixmap:
    """페이지 제목 아이콘 — 위치 핀 모양 아웃라인(다른 화면 제목 아이콘과
    같은 스트로크 스타일)."""
    scale = size / 24.0
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.8 * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def p(x, y):
        return QPointF(x * scale, y * scale)

    painter.drawLine(p(12, 22), p(5, 12.5))
    painter.drawLine(p(12, 22), p(19, 12.5))
    painter.drawEllipse(QRectF(5 * scale, 2 * scale, 14 * scale, 14 * scale))
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(9.5 * scale, 6.5 * scale, 5 * scale, 5 * scale))
    painter.end()
    return pixmap


class CityOrganizeScreen(QWidget):
    """검사 결과를 지도 위에 도시별로 보여주는 화면. 같은 검사 세션
    (gui/scan_session_window.py) 안에서만 쓰인다."""

    back_requested = Signal()
    organize_requested = Signal(str)  # "copy" | "move" — "정리하기" 클릭 시점의 방식
    # (도시 라벨, 클릭한 FileInfo, 그 도시 그룹 전체 FileInfo 목록)
    photo_selected = Signal(str, object, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[tuple[str, list[FileInfo]]] = []  # "위치 정보 없음" 제외 — 지도/목록 표시용
        self._no_gps_groups: list[tuple[str, list[FileInfo]]] = []  # "위치 정보 없음" 하나(있으면) — 정리 실행용
        self._files: list[FileInfo] = []  # 지도/목록에 쓸 GPS 있는 파일 전체(= _groups 합집합)
        self._file_to_label: dict[str, str] = {}  # path -> 소속 도시 라벨
        self._group_exclusions: dict[str, set[str]] = {}
        self._output_root: str = ""

        # 화면 전체를 쓰는 큰 창에서 내용이 창 끝까지 늘어나면 텅 빈 공간이
        # 남아 허전해 보인다(gui/date_organize_screen.py·gui/organize_hub_screen.py와
        # 같은 문제/수정) — 내용 폭을 한 번 고정(900px)하고 가운데 정렬한다.
        # 예전엔 이 컨테이너가 없어서 지도/목록만 창 끝까지 늘어나고 하단 카드/
        # 버튼은 따로 640px로 좁혀놔서 왼쪽에 따로 몰려 보였다(2026-09-10, 사용자
        # 리포트 — "하단부분이 안이뻐, 다른애들이랑 통일하자").
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(900)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(content, 100)
        root.addStretch(1)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(_pin_icon_pixmap(COLORS["primary"]))
        title_row.addWidget(title_icon)
        title = QLabel("도시별")
        title.setObjectName("Title")
        title_row.addWidget(title)
        title_row.addStretch(1)
        back_btn = QPushButton("← 뒤로")
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        outer.addLayout(title_row)

        hint = QLabel(
            "미리보기예요 — 아직 아무 파일도 옮기지 않았어요. GPS 위치가 있는 사진만 지도에 찍혀요"
            "(대략적인 위치). 휠로 확대/축소, 드래그로 이동하면 아래 목록이 그 범위 사진으로 바뀌어요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        self.map_view = CityMapView()
        self.map_view.setMinimumHeight(280)
        outer.addWidget(self.map_view, stretch=2)

        self.empty_label = QLabel("GPS 위치 정보가 있는 사진이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        outer.addWidget(self.empty_label)

        region_label = QLabel("이 범위 안의 사진")
        region_label.setStyleSheet("font-weight: 700;")
        outer.addWidget(region_label)

        self.region_list = QListWidget()
        self.region_list.setMaximumHeight(140)
        self.region_list.itemClicked.connect(self._on_item_clicked)
        outer.addWidget(self.region_list)

        self.map_view.view_changed.connect(self._refresh_region_list)

        # --- 하단: 방식 선택 + 저장 위치 + 실행 (gui/date_organize_screen.py와 동일 패턴) ---
        mode_card = QFrame()
        mode_card.setObjectName("Card")
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(18, 14, 18, 14)
        mode_layout.setSpacing(8)

        mode_header_row = QHBoxLayout()
        mode_header_row.setSpacing(8)
        mode_label = QLabel("정리 방식")
        mode_label.setStyleSheet("font-weight: 700;")
        mode_header_row.addWidget(mode_label)
        no_city_note = QLabel(f'"{NO_CITY_LABEL}" 사진들은 따로 "위치없음" 폴더에 모아요.')
        no_city_note.setWordWrap(True)
        no_city_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        mode_header_row.addWidget(no_city_note, stretch=1)
        mode_layout.addLayout(mode_header_row)

        mode_group = QButtonGroup(self)
        self.copy_radio = QRadioButton("복사 (원본은 그대로 두고 새 폴더에 사본 생성 — 기본값)")
        self.copy_radio.setChecked(True)
        mode_group.addButton(self.copy_radio)
        mode_layout.addWidget(self.copy_radio)

        self.move_radio = QRadioButton("이동 (원본이 새 폴더로 옮겨지고 원래 위치엔 안 남음)")
        self.move_radio.setStyleSheet(f"color: {COLORS['warning']};")
        mode_group.addButton(self.move_radio)
        mode_layout.addWidget(self.move_radio)

        mode_layout.addSpacing(14)
        output_caption = QLabel("저장 위치")
        output_caption.setStyleSheet("font-weight: 700;")
        mode_layout.addWidget(output_caption)

        output_row = QHBoxLayout()
        change_output_btn = QPushButton("변경")
        change_output_btn.clicked.connect(self._on_change_output_clicked)
        output_row.addWidget(change_output_btn)
        self.output_path_label = QLabel("")
        self.output_path_label.setWordWrap(True)
        self.output_path_label.setStyleSheet("font-size: 12px;")
        output_row.addWidget(self.output_path_label, stretch=1)
        mode_layout.addLayout(output_row)

        outer.addWidget(mode_card)

        self.organize_btn = QPushButton("이 방식대로 정리하기")
        self.organize_btn.setObjectName("Primary")
        self.organize_btn.setEnabled(False)
        self.organize_btn.clicked.connect(self._on_organize_clicked)
        outer.addWidget(self.organize_btn)

    # --- 외부에서 호출 --------------------------------------------------

    def set_result(self, result) -> None:
        """검사 결과에서 GPS가 있는 파일만 도시별로 묶어 지도/목록에 반영한다.
        위치 정보 없는 파일은 지도에 찍을 좌표가 없어 이 화면 대상에서
        빠지지만("위치없음" 폴더로는 "정리하기" 때 여전히 모인다), 다시
        들어와도 이전에 체크 해제해둔 제외 목록은 유지한다(같은 result면)."""
        if result is not getattr(self, "_result", None):
            self._group_exclusions = {}
        self._result = result

        all_groups = result.city_groups() if result and result.files else []
        self._groups = [(label, files) for label, files in all_groups if label != NO_CITY_LABEL]
        self._no_gps_groups = [(label, files) for label, files in all_groups if label == NO_CITY_LABEL]
        self._files = [f for _, files in self._groups for f in files]
        self._file_to_label = {f.path: label for label, files in self._groups for f in files}

        # "정리하기"는 지도에 못 찍는(GPS 없는) 사진도 포함해 스캔된 파일
        # 전체를 대상으로 한다(날짜별 정리와 같은 원칙) — 지도/목록만 GPS
        # 있는 사진으로 한정한다.
        has_organizable = bool(self._files) or bool(self._no_gps_groups)
        has_map_content = bool(self._files)
        self.map_view.setVisible(has_map_content)
        self.region_list.setVisible(has_map_content)
        self.empty_label.setVisible(not has_map_content)
        self.organize_btn.setEnabled(has_organizable)
        if not has_map_content:
            return

        self._refresh_map()
        self._refresh_region_list()

    def set_output_root(self, path: str) -> None:
        self._output_root = path
        self.output_path_label.setText(path)

    def output_root(self) -> str:
        return self._output_root

    def _visible_groups(self) -> list[tuple[str, list[FileInfo]]]:
        """체크 해제(제외)를 반영한 도시 그룹 — 지도 표시와 "정리하기" 실행
        대상 계산이 둘 다 이 기준을 쓴다."""
        result = []
        for label, files in self._groups:
            excluded = self._group_exclusions.get(label)
            if excluded:
                files = [f for f in files if f.path not in excluded]
            result.append((label, files))
        return result

    def groups(self) -> list[tuple[str, list[FileInfo]]]:
        """현재 도시 그룹(체크 해제/제외 반영) + "위치 정보 없음" 그룹을 합쳐
        반환한다 — "정리하기"를 실제로 실행할 호출부(gui/scan_session_window.py)가
        core/date_organizer.py::organize_by_city()에 그대로 넘길 수 있게.
        위치 정보 없는 사진은 지도/목록엔 안 보여도 "정리하기"에서는 함께
        "위치없음" 폴더로 모인다(gui/date_organize_screen.py와 같은 원칙 —
        스캔된 파일 전체가 실행 대상)."""
        return self._visible_groups() + self._no_gps_groups

    def group_excluded(self, label: str) -> set[str]:
        return set(self._group_exclusions.get(label, ()))

    def set_group_excluded(self, label: str, excluded_paths: set[str]) -> None:
        if excluded_paths:
            self._group_exclusions[label] = set(excluded_paths)
        else:
            self._group_exclusions.pop(label, None)
        # 그룹 상세에서 방금 체크 해제하고 돌아온 참일 수 있으니, 지도 위
        # 사진 개수 배지도 바로 갱신한다(제외된 사진 수만큼 줄어듦).
        self._refresh_map()

    def _refresh_map(self) -> None:
        visible_groups = [(label, files) for label, files in self._visible_groups() if files]
        map_points = [(files[0].latitude, files[0].longitude, len(files), label) for label, files in visible_groups]
        self.map_view.set_points(map_points)

    # --- 내부 로직 -----------------------------------------------------

    def _rows_in_view(self) -> list[FileInfo]:
        lat_min, lat_max, lon_min, lon_max = self.map_view.visible_bounds()
        return [
            f
            for f in self._files
            if lat_min <= f.latitude <= lat_max and lon_min <= f.longitude <= lon_max
        ]

    def _refresh_region_list(self) -> None:
        visible = self._rows_in_view()
        self.region_list.clear()
        for info in visible:
            item = QListWidgetItem(f"{info.filename} — {self._file_to_label.get(info.path, '')}")
            item.setData(Qt.UserRole, info)
            self.region_list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        info = item.data(Qt.UserRole)
        label = self._file_to_label.get(info.path)
        files = next((files for group_label, files in self._groups if group_label == label), [info])
        self.photo_selected.emit(label, info, files)

    def _on_change_output_clicked(self):
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self._output_root or "")
        if chosen:
            self.set_output_root(chosen)

    def _on_organize_clicked(self):
        mode = "move" if self.move_radio.isChecked() else "copy"
        self.organize_requested.emit(mode)
