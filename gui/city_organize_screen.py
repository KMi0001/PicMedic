"""
gui/city_organize_screen.py

Phase 2 "도시별 정리" — PHASE2_사진정리_기획.md "위치 시각화" + "뷰어 우선"
원칙 적용. gui/city_map_view.py 지도를 확대/이동하면 그 범위 안에 위치가
있는(실측 GPS 또는 core/location_inference.py로 추정된) 사진만 아래 목록에
보여주고, 목록에서 사진을 고르면
gui/date_group_detail_screen.py(뷰어 + 하단 썸네일 목록, 체크박스로 그룹에서
제외 가능)를 그대로 재사용해 자세히 볼 수 있다. gui/date_organize_screen.py와
같은 원칙으로 "정리하기"(복사/이동)도 지원한다 — 미리보기(지도 훑어보기)와
실행이 분리돼 있다.

목록에서 사진을 클릭하면 그 사진이 속한 "도시 그룹" 전체(현재 지도에 보이는
범위가 아니라)를 그룹 상세 화면에서 보여준다 — 체크 해제(제외)가 실제
"정리하기" 대상과 정확히 대응되게 하기 위함(지도 범위는 줌/팬마다 바뀌어서
그 자체를 그룹으로 삼으면 제외 목록이 무엇을 가리키는지 애매해진다).

실측 GPS도, 추정 위치도 없는 사진은 지도에 찍을 좌표가 없어 이 화면에는
안 보이지만, "정리하기"를 실행하면 core/date_organizer.py::organize_by_city()가
별도 폴더("위치없음")로 모아준다.
experiments/city_organize_prototype에서 지도/줌 부분을 먼저 검증함.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
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


class _CurrentOnlyStack(QStackedWidget):
    """gui/organize_hub_screen.py::_CurrentOnlyStack와 같은 이유로 필요 — 기본
    QStackedWidget/setVisible() 토글은 숨긴 페이지도 레이아웃 공간을 계속
    차지해서 빈 공간이 남거나(gui/duplicate_screen.py에서 실측 확인) 내용이
    엉뚱하게 늘어나는 문제가 있다. 지도/목록 ↔ "GPS 없음" 안내 전환에 쓴다."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class _ClickableFileRow(QLabel):
    """도시 카드 안 파일 한 줄 — gui/duplicate_screen.py::_ClickableLabel과
    같은 패턴. 클릭하면 상세보기, 우클릭하면 상세보기/로컬 폴더 위치 열기
    메뉴(2026-09-10, 사용자 요청)."""

    clicked = Signal()

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("font-size: 12px; padding: 2px 0;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
        # 지도 팬/줌마다(_refresh_region_list) 도시 카드를 통째로 다시
        # 그리므로, 펼쳐뒀던 카드가 어느 것인지 따로 기억해두지 않으면
        # 스크롤/줌 한 번에 다시 접혀버린다 — 도시를 선택(펼치기)하면
        # 지도도 그 위치로 이동하게 만들면서(2026-09-18, 사용자 요청)
        # 이동 자체가 새 view_changed를 일으켜 재구성을 유발하므로 특히
        # 중요해졌다.
        self._expanded_city_labels: set[str] = set()

        # 화면 전체를 쓰는 큰 창에서 내용이 창 끝까지 늘어나면 텅 빈 공간이
        # 남아 허전해 보인다(gui/date_organize_screen.py·gui/organize_hub_screen.py와
        # 같은 문제/수정) — 내용 폭을 한 번 고정하고 가운데 정렬한다. 지도와
        # 목록을 좌우로 나란히 놓으면서(2026-09-10, 사용자 요청) 900px로는
        # 목록 칸이 너무 좁아져 1100px로 넓혔다(gui/organize_hub_screen.py가
        # 표+뷰어를 추가하며 760→1080으로 넓힌 것과 같은 이유).
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(1100)
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
            "미리보기예요 — 아직 아무 파일도 옮기지 않았어요. GPS 위치가 있는 사진과, GPS는 없지만 "
            "촬영 시각·비슷한 사진으로 위치를 추정한 사진이 지도에 찍혀요(대략적인 위치, 추정 위치는 "
            "목록에 따로 표시). 휠로 확대/축소, 드래그로 이동하면 아래 목록이 그 범위 사진으로 바뀌어요."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        outer.addWidget(hint)

        # --- 지도(왼쪽) | 목록(오른쪽), 도시별로 묶어서 카드로 보여준다
        # (2026-09-10, 사용자 요청 — "지도|목록 이렇게 보이게 배치 바꾸고
        # 같은 도시면 중복 사진처럼 묶어줘". gui/duplicate_screen.py의
        # 그룹 카드 패턴 재사용). GPS 있는 사진이 아예 없으면 이 영역 전체를
        # empty_label로 바꿔치기한다 — setVisible() 토글은 레이아웃 공간을
        # 예측 불가능하게 남기는 문제가 있어(gui/duplicate_screen.py에서
        # 실측 확인) _CurrentOnlyStack으로 완전히 교체한다.
        self.map_list_widget = QWidget()
        map_list_row = QHBoxLayout(self.map_list_widget)
        map_list_row.setContentsMargins(0, 0, 0, 0)
        map_list_row.setSpacing(16)

        self.map_view = CityMapView()
        self.map_view.setMinimumHeight(360)
        map_list_row.addWidget(self.map_view, stretch=3)

        list_col = QVBoxLayout()
        list_col.setSpacing(8)
        region_label = QLabel("이 범위 안의 사진")
        region_label.setStyleSheet("font-weight: 700;")
        list_col.addWidget(region_label)

        self.region_scroll = QScrollArea()
        self.region_scroll.setWidgetResizable(True)
        self.region_scroll.setFrameShape(QFrame.NoFrame)
        self.region_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._region_container = QWidget()
        self._region_layout = QVBoxLayout(self._region_container)
        self._region_layout.setContentsMargins(0, 0, 0, 0)
        self._region_layout.setSpacing(10)
        self._region_layout.addStretch(1)
        self.region_scroll.setWidget(self._region_container)
        list_col.addWidget(self.region_scroll, stretch=1)

        self.region_empty_label = QLabel("이 범위에 GPS 사진이 없어요 — 지도를 움직여보세요.")
        self.region_empty_label.setWordWrap(True)
        self.region_empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; padding: 12px 0;")
        list_col.addWidget(self.region_empty_label)

        map_list_row.addLayout(list_col, stretch=2)

        self.empty_label = QLabel("GPS 위치 정보가 있는 사진이 없습니다.")
        self.empty_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 24px;")
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.content_stack = _CurrentOnlyStack()
        self.content_stack.addWidget(self.map_list_widget)
        self.content_stack.addWidget(self.empty_label)
        outer.addWidget(self.content_stack, stretch=1)

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
            self._expanded_city_labels = set()
            self.map_view.reset_initial_view()
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
        self.content_stack.setCurrentWidget(self.map_list_widget if has_map_content else self.empty_label)
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
        from core.geocoder import resolve_country_codes, resolve_province_names

        visible_groups = [(label, files) for label, files in self._visible_groups() if files]
        # 그룹의 대표 좌표로 files[0](그룹의 첫 파일)만 썼더니 실제 버그로
        # 이어졌다 — 서울 그룹인데 하필 첫 파일의 GPS가(사진 촬영 순서상
        # 우연히) 인천 쪽에 가까우면 지도 핀 자체가 인천 근처에 찍히고,
        # 그 핀을 클릭(포커스)하면 그 잘못된 좌표로 확대돼 "서울을 선택하면
        # 인천으로 포커싱된다"는 리포트로 나타났다(2026-09-18). 그룹 전체
        # 파일의 GPS 평균(중심점)을 쓰면 한두 개의 튀는 좌표에 덜 휘둘린다.
        centroids = [self._group_centroid(files) for _, files in visible_groups]
        country_codes = resolve_country_codes(centroids) if centroids else []
        provinces = resolve_province_names(centroids) if centroids else []
        map_points = [
            (*centroid, len(files), label, cc, province)
            for (label, files), centroid, cc, province in zip(visible_groups, centroids, country_codes, provinces)
        ]
        self.map_view.set_points(map_points)

    @staticmethod
    def _group_centroid(files: list[FileInfo]) -> tuple[float, float]:
        """도시 그룹 안 모든 파일의 GPS 평균 — 지도 핀 위치/나라·시도 판정에
        쓰는 그룹의 대표 좌표. 파일 하나(특히 files[0])만 대표로 쓰면 그
        파일이 우연히 그룹 라벨과 안 맞는 위치일 때(예: "서울" 그룹의
        일부 사진이 인천 경계 근처) 핀 자체가 엉뚱한 곳에 찍힌다."""
        locations = [loc for f in files if (loc := f.effective_location())]
        avg_lat = sum(lat for lat, _lon in locations) / len(locations)
        avg_lon = sum(lon for _lat, lon in locations) / len(locations)
        return (avg_lat, avg_lon)

    # --- 내부 로직 -----------------------------------------------------

    def _rows_in_view(self) -> list[FileInfo]:
        lat_min, lat_max, lon_min, lon_max = self.map_view.visible_bounds()
        rows = []
        for f in self._files:
            location = f.effective_location()
            if location is None:
                continue
            lat, lon = location
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                rows.append(f)
        return rows

    def _refresh_region_list(self) -> None:
        """지도에 보이는 범위 안 사진을(_rows_in_view) 도시별로 묶어 카드로
        다시 그린다 — gui/duplicate_screen.py::set_result과 같은 "통째로 다시
        만들기" 방식(그룹 몇 개 안 되는 화면이라 매번 다시 그려도 충분히 가볍다)."""
        visible_paths = {info.path for info in self._rows_in_view()}

        while self._region_layout.count() > 1:
            item = self._region_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        any_group = False
        for label, files in self._groups:
            group_files = [f for f in files if f.path in visible_paths]
            if not group_files:
                continue
            any_group = True
            card = self._build_city_card(label, group_files)
            self._region_layout.insertWidget(self._region_layout.count() - 1, card)

        self.region_empty_label.setVisible(not any_group)

    # 한 도시 카드에 파일 행을 이 개수까지만 그린다 — 실사용(4만 6천 장)
    # 리포트: 사진이 몰린 도시(예: "서울" 수천~수만 장) 카드 하나를 만드는
    # 데만 실측 2초 가까이 걸려서, 팬/줌마다(디바운스해도) 이게 다시 돌면
    # 여전히 느리게 느껴졌다(2026-09-17). 행 위젯 수 자체를 제한해서 카드
    # 생성 비용의 상한을 건다 — 도시 카드는 "훑어보기"용이라 몇 장인지
    # 정확한 파일명 목록 전부가 항상 필요하진 않다는 판단.
    _MAX_FILE_ROWS_PER_CARD = 200

    def _build_city_card(self, label: str, files: list[FileInfo]) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        inferred_count = sum(1 for f in files if f.location_inferred_from)
        header_text = f"{label} · {len(files)}장"
        if inferred_count:
            header_text += f" (그중 {inferred_count}장은 추정 위치)"

        # 카드 자체를 기본으로 접어둔다 — 지도에 보이는 도시가 여러 개면
        # 카드마다 파일 목록이 다 펼쳐진 채로 쌓여서 화면을 감당 안 될
        # 만큼 길게 만들었다(2026-09-18, 사용자 리포트: "접기(그룹화)를
        # 안 만들어주는거야"). 헤더를 눌러야 그 도시의 파일 목록을 펼치고,
        # 그때 처음으로 행 위젯을 만든다(_MAX_FILE_ROWS_PER_CARD를 둔
        # 이유였던 카드 생성 비용이, 접혀 있는 동안은 여러 도시 카드가
        # 동시에 화면에 있어도 전혀 들지 않는다).
        header_btn = QToolButton()
        header_btn.setCheckable(True)
        header_btn.setAutoRaise(True)
        header_btn.setCursor(Qt.PointingHandCursor)
        header_btn.setText(f"▸ {header_text}")
        header_btn.setStyleSheet("QToolButton { border: none; background: transparent; "
                                  "text-align: left; font-weight: 700; }")
        layout.addWidget(header_btn)

        body = QWidget()
        # 전역 `QWidget { background-color: ... }` 규칙(gui/theme.py) 때문에
        # 아무 스타일도 안 주면 이 컨테이너가 카드 배경(surface)과 다른
        # 페이지 배경색(bg)으로 칠해져 카드 안에 이질적인 배경 패치가
        # 생긴다 — 카테고리 배지 컨테이너에서 이미 한 번 겪은 것과 같은
        # 버그 패턴(2026-09-18, 사용자 리포트: "목록에 배경색이 들어간다").
        body.setStyleSheet("background-color: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(4)
        body.setVisible(False)
        layout.addWidget(body)

        built = {"done": False}

        def _on_header_toggled(checked: bool) -> None:
            if checked:
                self._expanded_city_labels.add(label)
                if not built["done"]:
                    self._populate_city_card_body(body_layout, files, label)
                    built["done"] = True
            else:
                self._expanded_city_labels.discard(label)
            body.setVisible(checked)
            header_btn.setText(("▾ " if checked else "▸ ") + header_text)

        def _on_header_clicked(checked: bool) -> None:
            # toggled와 달리 clicked는 실제 사용자 클릭에서만 오고, 지도
            # 이동을 재구성(_refresh_region_list, 이 카드를 다시 만들며
            # 이전 펼침 상태를 setChecked로 복원할 때)에서는 안 온다 —
            # 그래서 복원 중에 지도가 다시 튀는 걸 막는 용도로 이 신호를
            # 따로 쓴다(2026-09-18, 사용자 요청: "마카오 선택하면 마카오로
            # 지도를 움직였으면 좋겠는데").
            if not checked:
                return
            locations = [loc for f in files if (loc := f.effective_location())]
            if locations:
                self.map_view.focus_on_locations(locations)

        header_btn.toggled.connect(_on_header_toggled)
        header_btn.clicked.connect(_on_header_clicked)

        if label in self._expanded_city_labels:
            header_btn.setChecked(True)

        return card

    def _populate_city_card_body(self, layout: QVBoxLayout, files: list[FileInfo], label: str) -> None:
        """도시 카드가 처음 펼쳐질 때 딱 한 번만 불린다(_build_city_card 참고).
        파일 행 개수 상한과 상한 넘는 파일의 "더 보기" 토글은 카드 접기/펴기
        기능이 생기기 전부터 있던 동작 그대로다."""
        shown_files = files[: self._MAX_FILE_ROWS_PER_CARD]
        for info in shown_files:
            layout.addWidget(self._build_file_row(info, label))

        remaining_files = files[self._MAX_FILE_ROWS_PER_CARD :]
        if remaining_files:
            # 상한 넘는 파일은 마찬가지로 접어둔다 — 실제로 위젯을 만드는
            # 건 사용자가 "더 보기"를 눌렀을 때 딱 한 번만(2026-09-17,
            # 사용자 요청 — "목록의 접기펴기는 왜 구현이 안된거야").
            toggle_btn = QToolButton()
            toggle_btn.setCheckable(True)
            toggle_btn.setAutoRaise(True)
            toggle_btn.setCursor(Qt.PointingHandCursor)
            toggle_btn.setText(f"▸ 외 {len(remaining_files):,}장 더 보기")
            toggle_btn.setStyleSheet(
                f"QToolButton {{ border: none; background: transparent; text-align: left; "
                f"color: {COLORS['text_secondary']}; font-size: 11px; }}"
            )
            layout.addWidget(toggle_btn)

            extra_rows: list[QWidget] = []

            def _on_toggled(checked: bool, btn=toggle_btn) -> None:
                if checked and not extra_rows:
                    for info in remaining_files:
                        row = self._build_file_row(info, label)
                        layout.addWidget(row)
                        extra_rows.append(row)
                    # 방금 끝에 추가한 행들 뒤로 토글 버튼을 다시 옮긴다 —
                    # "더 보기"는 항상 이 카드의 마지막 줄이어야 한다.
                    layout.removeWidget(btn)
                    layout.addWidget(btn)
                for row in extra_rows:
                    row.setVisible(checked)
                btn.setText("▾ 접기" if checked else f"▸ 외 {len(remaining_files):,}장 더 보기")

            toggle_btn.toggled.connect(_on_toggled)

    def _build_file_row(self, info: FileInfo, label: str) -> _ClickableFileRow:
        row_text = info.filename
        if info.location_inferred_from:
            row_text += f"  (추정 위치 · {info.location_inferred_from})"
        row = _ClickableFileRow(row_text)
        row.setToolTip(info.path)
        row.clicked.connect(lambda info=info, label=label: self._open_detail(label, info))
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, w=row, info=info, label=label: self._on_row_context_menu(w, pos, info, label)
        )
        return row

    def _open_detail(self, label: str, info: FileInfo) -> None:
        files = next((files for group_label, files in self._groups if group_label == label), [info])
        self.photo_selected.emit(label, info, files)

    def _on_row_context_menu(self, widget: QWidget, pos, info: FileInfo, label: str) -> None:
        menu = QMenu(self)
        detail_action = menu.addAction("상세보기")
        open_folder_action = menu.addAction("로컬 폴더 위치 열기")
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is detail_action:
            self._open_detail(label, info)
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(info.path).parent)))

    def _on_change_output_clicked(self):
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", self._output_root or "")
        if chosen:
            self.set_output_root(chosen)

    def _on_organize_clicked(self):
        mode = "move" if self.move_radio.isChecked() else "copy"
        self.organize_requested.emit(mode)
