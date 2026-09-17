"""
gui/city_map_view.py

Phase 2 "도시별 정리"용 지도 — 휠로 확대/축소, 드래그로 이동되는 정적
세계 지도(PHASE2_사진정리_기획.md "위치 시각화" 절: QtWebEngine/실제 지도
타일 없이 Natural Earth 국가 경계만 그린다). experiments/city_organize_prototype
에서 먼저 검증됨 — "한국 위주로 보여주고 확대/축소가 됐으면 좋겠다"는
사용자 피드백으로 최초 기획(고정 지도)에서 줌/팬 가능하도록 바뀌었고,
gui/image_viewer.py::_ZoomPanView와 같은 QGraphicsView 기반 원리를 쓴다.
이후 "나라/지명 정도는 나오게" 피드백으로 나라 윤곽(국경선) + 이름 라벨도
추가했다(2026-09-08).

씬 좌표계 = 경위도 그대로(x=경도, y=-위도 — Qt는 y가 아래로 갈수록 커지므로
북쪽이 위로 오게 부호를 뒤집는다). 국가 경계 데이터는
assets/world_countries_50m.json(Natural Earth 1:50m, 퍼블릭 도메인 —
topojson/world-atlas가 TopoJSON으로 재배포, ISC 유사 라이선스)를
utils/topojson.py로 디코딩해서 그린다. 나라 이름은 core/country_names_ko.py로
한국어로 보여주고(없으면 원문), 화면에서 그 나라가 차지하는 크기가 어느
정도(=충분히 확대됐을 때)일 때만 라벨을 보여줘서 세계 전체를 볼 때 이름이
빽빽하게 겹치지 않게 한다."""

from __future__ import annotations

import zlib

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QToolButton, QWidget

from core.country_names_ko import COUNTRY_NAMES_KO
from core.geocoder import country_name_ko
from utils.assets import asset_path
from utils.topojson import load_country_polygons

_COUNTRIES_PATH = asset_path("world_countries_50m.json")
KOREA_CENTER = (36.5, 127.8)  # 초기 지도 중심(대략 대한민국 중앙)

_OCEAN_COLOR = "#DCEEF5"
_LAND_FILL_COLOR = "#CDE8DC"
_LAND_BORDER_COLOR = "#9FC6B0"
_COUNTRY_LABEL_COLOR = QColor(90, 120, 105, 200)

# 핀 색상 팔레트 — 예전엔 전부 같은 빨간색이었는데 "핀 색상을 좀 다양하게
# 할 수 있나?"(2026-09-18)로 나라코드별로 색을 달리했다가, 바로 이어서
# "핀 색상은 도시별로 바꿔줘"로 다시 바뀌었다 — 지금은 마커가 실제로
# 대표하는 단위 자체(도시 라벨/시도 (나라,시도) 쌍/나라 코드 — 어느 걸
# 보든 그 마커의 고유 식별자)로 색을 나눈다(_marker_color_for_key 참고).
# 옅은 바다(#DCEEF5)/땅(#CDE8DC) 배경 위에서 잘 도드라지도록 채도를
# 충분히 준 8가지 색.
_MARKER_PALETTE = [
    QColor(218, 90, 90, 210),   # 빨강 (기존 기본색 유지)
    QColor(74, 120, 196, 210),  # 파랑
    QColor(217, 138, 43, 210),  # 주황
    QColor(123, 95, 196, 210),  # 보라
    QColor(30, 156, 110, 210),  # 초록
    QColor(194, 78, 134, 210),  # 핑크
    QColor(42, 166, 166, 210),  # 청록
    QColor(166, 124, 46, 210),  # 갈색
]


def _marker_color_for_key(key) -> QColor:
    """마커 하나를 특정하는 값(도시 라벨, (나라코드, 시/도) 쌍, 나라 코드
    등 — 그 마커가 화면에 실제로 대표하는 단위)마다 항상 같은 색을
    돌려준다. Python 내장 hash()는 프로세스마다 시드가 달라 같은 값도
    실행할 때마다 색이 바뀔 수 있어서(해시 랜덤화), 대신 결정적인 crc32를
    쓴다."""
    if not key:
        return _MARKER_PALETTE[0]
    index = zlib.crc32(str(key).encode("utf-8")) % len(_MARKER_PALETTE)
    return _MARKER_PALETTE[index]

# 나라 이름 라벨을 보여줄 최소 화면 크기(px) — 이보다 작게 보이면(세계 전체를
# 보는 중이라 그 나라가 작게 보이면) 숨긴다. 확대할수록 큰 나라부터, 더
# 확대하면 작은 나라까지 순서대로 나타난다.
_COUNTRY_LABEL_MIN_PX = 50

# 지도 위에 얹는 컨트롤 버튼(재중심/확대/축소) 스타일 — gui/image_viewer.py의
# 오버레이 툴바(_OVERLAY_TOOLBAR_STYLESHEET)와 같은 반투명 알약 스타일
# (2026-09-17, 사용자 요청: "gps를 추적할 순 없으니까 사진이 가장 많은 나라
# 기준으로 지도를 표기해주는 버튼이랑 +/- 확대 축소 버튼").
_MAP_OVERLAY_STYLESHEET = (
    "QWidget#MapOverlayToolbar {"
    " background-color: rgba(20, 18, 15, 150);"
    " border-radius: 16px;"
    "}"
    "QToolButton {"
    " background: transparent;"
    " border: none;"
    " color: white;"
    "}"
    "QToolButton:hover {"
    " background-color: rgba(255, 255, 255, 40);"
    " border-radius: 8px;"
    "}"
    "QToolButton:disabled {"
    " color: rgba(255, 255, 255, 90);"
    "}"
)


def _ring_area_and_centroid(ring: list[tuple[float, float]]) -> tuple[float, tuple[float, float]]:
    """신발끈 공식(shoelace formula)으로 다각형 면적과 무게중심을 구한다 —
    나라 이름 라벨을 그 나라에서 가장 큰 땅덩어리(섬나라의 작은 부속 도서가
    아니라 본토) 위에 앉히기 위함."""
    area = 0.0
    cx = 0.0
    cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    if abs(area) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return 0.0, (sum(xs) / len(xs), sum(ys) / len(ys))
    cx /= 6 * area
    cy /= 6 * area
    return abs(area), (cx, cy)


def _bounding_rect(ring: list[tuple[float, float]]) -> QRectF:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class _CityMarker(QGraphicsItem):
    """지도 위 도시 점 하나 — 원 + 라벨. ItemIgnoresTransformations를 켜서
    지도를 확대/축소해도 화면상 크기(점, 글자)는 항상 일정하게 유지된다
    (좌표만 지도 줌/팬을 따라간다). 원과 라벨을 한 아이템 안에서 같이
    그려야 줌 배율이 달라져도 라벨 오프셋이 어긋나지 않는다.

    라벨 겹침 방지(CityMapView._layout_labels)가 원 위치는 그대로 두고
    라벨만 위아래로 밀어낼 수 있도록 label_dy를 별도로 둔다."""

    # boundingRect가 커버해야 하는 라벨 위아래 최대 오프셋 — _layout_labels의
    # 후보 목록(최대 ±64)보다 여유 있게 잡아서 화면에서 잘려 보이지 않게 한다.
    _MAX_LABEL_DY = 80

    def __init__(self, radius: float, label: str, color: QColor = _MARKER_PALETTE[0]):
        super().__init__()
        self._radius = radius
        self._label = label
        self._color = color
        self._label_dy = 0.0
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(10)
        self.setCursor(Qt.PointingHandCursor)
        # 이 아이템이 왼쪽 버튼 press/release를 아예 안 받게 한다 — 받으면
        # (설령 ignore()해도) CityMapView의 기본 드래그 패닝(ScrollHandDrag)이
        # 핀 위에서 시작할 땐 실제로 안 먹히는 걸 실측으로 확인했다(2026-09-17,
        # 사용자 리포트 — "핀 위에서 드래그하면 확대되고 패닝이 안 됨"). 클릭
        # 판정은 CityMapView.mouseReleaseEvent가 itemAt()으로 직접 하므로
        # (아래 mousePressEvent 삭제, contextMenuEvent만 남김) 이 아이템이
        # 마우스 이벤트를 안 받아도 클릭은 그대로 인식된다 — itemAt()은
        # acceptedMouseButtons와 무관하게 순수 도형 히트테스트다.
        self.setAcceptedMouseButtons(Qt.NoButton)
        # CityMapView가 마커를 만든 직후 채워준다 — 좌클릭(그 지역으로 확대,
        # "핀 열기") / 우클릭(전체 보기로 축소, "핀 닫기") 둘 다 이 마커가
        # 뭘 대표하는지 CityMapView만 알기 때문에, 콜백을 주입받는 방식으로
        # 뷰 쪽 로직과 분리한다(2026-09-17, 사용자 요청).
        self.on_left_click = None
        self.on_right_click = None

    def radius(self) -> float:
        return self._radius

    def label_text(self) -> str:
        return self._label

    def set_label_dy(self, dy: float) -> None:
        if dy == self._label_dy:
            return
        self.prepareGeometryChange()
        self._label_dy = dy
        self.update()

    def boundingRect(self) -> QRectF:
        top = -self._radius - self._MAX_LABEL_DY
        height = self._radius * 2 + self._MAX_LABEL_DY * 2
        return QRectF(-self._radius, top, self._radius * 2 + 220, height)

    def shape(self) -> QPainterPath:
        """boundingRect()는 라벨 텍스트 영역(원 오른쪽으로 최대 220 단위,
        위아래로 라벨이 밀렸을 때 대비 ±80 단위)까지 넉넉히 잡는다 —
        update()/repaint 범위 계산용으로는 맞는데, shape()를 따로 안 주면
        Qt가 기본으로 boundingRect() 전체를 클릭 판정 영역으로 쓴다
        (QGraphicsItem 문서). 그러면 마커 여러 개가 가까이 있을 때(특히
        나라/세계지도 단위로 줌아웃했을 때) 한 마커의 "보이지도 않는" 라벨
        영역이 옆 마커의 눈에 보이는 원 위까지 뒤덮어서, 분명 A를 눌렀는데
        겹친 B의 라벨 영역이 위 스택에 있으면 B가 클릭된 걸로 잡혔다 —
        "서울 선택하면 인천으로", "대한민국 선택해도 대만으로 가고 있다"는
        리포트의 실제 원인(2026-09-18). 실제로 보이는 원만 클릭 판정
        영역으로 좁힌다."""
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), self._radius, self._radius)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QPointF(0, 0), self._radius, self._radius)

        label_pos = QPointF(self._radius + 4, 4 + self._label_dy)
        if self._label_dy != 0:
            # 라벨이 원에서 떨어져 있으면 점선으로 어느 원의 라벨인지 이어준다.
            pen = QPen(QColor("#8a8a8a"))
            pen.setStyle(Qt.DashLine)
            pen.setWidthF(1)
            painter.setPen(pen)
            painter.drawLine(QPointF(0, 0), QPointF(0, label_pos.y() - 4))
            painter.drawLine(QPointF(0, label_pos.y() - 4), QPointF(self._radius + 2, label_pos.y() - 4))
        painter.setPen(QColor("#222"))
        painter.drawText(label_pos, self._label)

    def contextMenuEvent(self, event) -> None:
        if self.on_right_click is not None:
            self.on_right_click(event.screenPos())
            event.accept()
            return
        super().contextMenuEvent(event)


class _CountryLabel(QGraphicsItem):
    """나라 이름 라벨 — 화면 크기 일정(ItemIgnoresTransformations), 도시
    마커보다 아래(zValue)라 겹쳐도 도시 정보가 우선 보인다. 표시 여부는
    CityMapView._update_country_label_visibility가 화면상 그 나라 크기를
    보고 켜고 끈다(작게 보일 땐 숨김 — 겹침 방지 겸 정보 과잉 방지)."""

    def __init__(self, name: str):
        super().__init__()
        self._name = name
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(1)
        font = QFont()
        font.setItalic(True)
        font.setPointSizeF(font.pointSizeF() * 0.95)
        self._font = font

    def boundingRect(self) -> QRectF:
        fm = QFontMetrics(self._font)
        width = fm.horizontalAdvance(self._name) + 8
        height = fm.height() + 4
        return QRectF(-width / 2, -height / 2, width, height)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self._font)
        painter.setPen(_COUNTRY_LABEL_COLOR)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self._name)


class CityMapView(QGraphicsView):
    """줌(휠)·팬(드래그)이 되는 세계 지도."""

    view_changed = Signal()  # 줌/팬이 끝날 때마다(보이는 범위가 바뀔 때마다) 발생

    _MIN_SCALE = 1.5   # 세계 전체가 겨우 들어오는 수준
    # 이 지도는 실제 지도 타일이 아니라 국가 윤곽선만 그린 정적 지도라(위
    # 클래스 독스트링 참고), 너무 깊이 확대해봤자 거리·건물 같은 참고할
    # 지형지물이 하나도 없는 빈 배경만 보여서 오히려 방향을 잃는다. 정확한
    # 적정값을 한 번에 못 맞춰서 2026-09-18 하루 동안만 여러 번 오갔다 —
    # 1600(2026-09-17 최초값, "시/도 하나 크기") → 643("[-] 다섯 번") →
    # 258("[-] 다섯 번 더") → 다시 372("[+] 두 번", 이번). 매번 줌 버튼
    # 한 번(×1.2, _zoom_by 참고)을 기준 삼아 사용자가 직접 준 "몇 번"을
    # 그대로 식으로 옮겼다 — 원래 1600 기준으로 순 [-] 여덟 번인 셈.
    _MAX_SCALE = 1600.0 / (1.2**8)  # ≈ 372

    def __init__(self, parent=None):
        scene = QGraphicsScene(-180, -90, 360, 180)
        # PySide6는 뷰가 씬의 소유권을 가져가지 않는다 — self._scene으로 파이썬
        # 참조를 안 잡아두면 생성자 종료 직후 GC가 씬을 회수해 self.scene()이
        # 조용히 None이 된다(experiments/city_organize_prototype에서 확인된 버그).
        self._scene = scene
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        scene.setBackgroundBrush(QColor(_OCEAN_COLOR))

        # 드래그로 팬 하는 동안 scrollContentsBy가 픽셀 단위로 계속 불려서
        # view_changed도 그만큼 자주(초당 수십 번) 발생한다 — 도시가 수십 개
        # (실사용 4만 6천 장 규모 리포트)면 _rebuild_markers/_layout_labels가
        # 매번 그 전부를 다시 계산해서 드래그 중 응답 없음처럼 보였다
        # (2026-09-17, 사용자 리포트). gui/image_viewer.py::_refit_timer와
        # 같은 이유로, 실제 재계산은 마지막 이벤트 뒤 잠깐(디바운스) 멈췄을
        # 때만 한다 — wheelEvent/scrollContentsBy가 직접 view_changed를
        # emit하지 않고 이 타이머를 재시작하도록 바꿨다.
        #
        # 이 타이머는 반드시 아래 국가 경계 scene.addItem() 루프보다 먼저
        # 만들어야 한다 — addItem이 스크롤 영역을 재계산하며 Qt가 내부적으로
        # scrollContentsBy를 먼저 부를 수 있어서, 늦게 만들면 그 시점에
        # "_view_changed_timer가 없다" AttributeError가 난다(2026-09-17,
        # 핀 클릭 기능 추가 중 테스트로 발견).
        self._view_changed_timer = QTimer(self)
        self._view_changed_timer.setSingleShot(True)
        self._view_changed_timer.setInterval(120)
        self._view_changed_timer.timeout.connect(self.view_changed.emit)

        # (나라 이름, 라벨을 놓을 위경도 지점, 라벨이 대표하는 땅덩어리의
        # 위경도 바운딩박스 — 화면에서 이 박스가 얼마나 큰지로 라벨 표시 여부를 정한다)
        self._country_anchors: list[tuple[_CountryLabel, tuple[float, float], QRectF]] = []

        try:
            countries = load_country_polygons(_COUNTRIES_PATH)
        except Exception as exc:
            print("국가 경계 데이터 로드 실패:", exc)
            countries = []

        land_path = QPainterPath()
        for name, rings in countries:
            best_area = -1.0
            best_centroid = None
            best_bbox = None
            for ring in rings:
                if len(ring) < 3:
                    continue
                sub = QPainterPath()
                sub.moveTo(ring[0][0], -ring[0][1])
                for lon, lat in ring[1:]:
                    sub.lineTo(lon, -lat)
                sub.closeSubpath()
                land_path.addPath(sub)

                area, (cx, cy) = _ring_area_and_centroid(ring)
                if area > best_area:
                    best_area = area
                    best_centroid = (cx, cy)
                    best_bbox = _bounding_rect(ring)

            if best_centroid is None:
                continue
            label_text = COUNTRY_NAMES_KO.get(name, name)
            label_item = _CountryLabel(label_text)
            lon, lat = best_centroid
            label_item.setPos(lon, -lat)
            label_item.setVisible(False)
            scene.addItem(label_item)
            self._country_anchors.append((label_item, (lat, lon), best_bbox))

        scene.addPath(land_path, QPen(QColor(_LAND_BORDER_COLOR), 0.05), QColor(_LAND_FILL_COLOR))
        for label_item, _, _ in self._country_anchors:
            label_item.setZValue(1)  # addPath로 새로 그린 육지 위로 라벨이 오게 다시 확인

        self._markers: list[_CityMarker] = []
        self._raw_points: list[tuple[float, float, int, str, str]] = []
        # "도시 단위" / "나라 단위(2개국 이상 보일 때)" 중 지금 뭘 그리고
        # 있는지 — 팬/줌마다(_rebuild_markers) 매번 마커를 다시 만들면 드래그
        # 중 버벅일 수 있어서, 이 값이 실제로 바뀔 때만 다시 만든다.
        self._marker_mode: str | None = None
        self._centered_once = False
        # 실제 데이터(set_points)가 처음 들어왔을 때 딱 한 번만 전체 데이터가
        # 다 보이게 맞춘다 — "나라별로 있으면 지도에 다 보이기로 하지
        # 않았나?"(2026-09-18) 리포트로 발견: resizeEvent가 뷰가 뜨자마자
        # (스캔 결과가 아직 없을 때) _centered_once를 소비해버려서, 나중에
        # set_points로 진짜 데이터(예: 한국+유럽+미국)가 들어와도 다시는
        # 자동으로 맞춰주지 않고 KOREA_CENTER의 좁은 14도 박스에 그대로
        # 머물러 있었다 — 그 박스 밖 나라들은 뷰포트에 안 걸려서
        # _visible_points()에도 안 잡히니 나라 단위 집계 자체가 그 나라들을
        # 아예 없는 셈 쳤다.
        self._data_view_fitted = False
        self.view_changed.connect(self._rebuild_markers)
        self.view_changed.connect(self._update_country_label_visibility)

        # 핀 클릭("열기")을 눌렀다 뗀 위치가 거의 안 움직였을 때만 클릭으로
        # 인정하기 위한 상태 — _CityMarker.mousePressEvent가 press를 일부러
        # ignore()해서 뷰가 press/release를 둘 다 받으므로, 클릭 판정은 여기
        # (뷰 레벨)에서 한다.
        self._marker_press_pos = None

        self._build_overlay_toolbar()

    def _build_overlay_toolbar(self) -> None:
        """지도 안(오른쪽 아래)에 재중심/확대/축소 버튼 3개를 얹는다 — 실시간
        GPS 위치를 추적할 수 없는 데스크톱 앱이라 "지금 내 위치로" 대신
        "사진이 가장 많은 나라로" 재중심하는 버튼을 대신 둔다(2026-09-17,
        사용자 요청). gui/image_viewer.py의 오버레이 툴바와 같은 패턴 —
        일반 레이아웃에 안 넣고 self를 부모로 둔 채 resizeEvent에서 위치를
        직접 잡는다."""
        self._overlay_toolbar = QWidget(self)
        self._overlay_toolbar.setObjectName("MapOverlayToolbar")
        self._overlay_toolbar.setStyleSheet(_MAP_OVERLAY_STYLESHEET)
        layout = QHBoxLayout(self._overlay_toolbar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        def _btn(text: str, tooltip: str) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tooltip)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(26, 22)
            layout.addWidget(b)
            return b

        self._recenter_btn = _btn("⌂", "사진이 가장 많은 나라로 이동")
        self._zoom_in_btn = _btn("+", "확대")
        self._zoom_out_btn = _btn("－", "축소")
        self._recenter_btn.clicked.connect(self._recenter_to_busiest_country)
        self._zoom_in_btn.clicked.connect(lambda: self._zoom_by(1.2))
        self._zoom_out_btn.clicked.connect(lambda: self._zoom_by(1 / 1.2))

        self._overlay_toolbar.adjustSize()
        self._position_overlay_toolbar()

    def _position_overlay_toolbar(self) -> None:
        self._overlay_toolbar.adjustSize()
        margin = 14
        x = self.width() - self._overlay_toolbar.width() - margin
        y = self.height() - self._overlay_toolbar.height() - margin
        self._overlay_toolbar.move(max(0, x), max(0, y))
        self._overlay_toolbar.raise_()

    def _zoom_by(self, factor: float) -> None:
        """+/- 버튼 — wheelEvent와 같은 배율(1.2배)을 그대로 써서 휠로
        돌렸을 때와 손맛이 같게 한다."""
        new_scale = self.transform().m11() * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self.scale(factor, factor)
            self._start_view_changed_timer()

    def _country_with_most_photos(self) -> str | None:
        totals: dict[str, int] = {}
        for _lat, _lon, count, _label, cc, _province in self._raw_points:
            totals[cc] = totals.get(cc, 0) + count
        if not totals:
            return None
        return max(totals, key=totals.get)

    def _recenter_to_busiest_country(self) -> None:
        """실시간 GPS 위치를 알 수 없으니, 대신 사진이 가장 많이 찍힌 나라를
        "내 위치" 삼아 그 나라 사진들이 화면에 꽉 차게 재중심한다."""
        busiest_cc = self._country_with_most_photos()
        if busiest_cc is None:
            self.center_on(*KOREA_CENTER)
            return
        member_points = [
            (lat, lon) for lat, lon, _count, _label, cc, _province in self._raw_points if cc == busiest_cc
        ]
        self._fit_scene_rect(self._points_bounds(member_points))

    # 한 나라 안에서도 화면에 보이는 도시 마커가 이 개수를 넘으면 시/도
    # 단위로 한 단계 더 뭉친다 — 국내 사진만 수만 장이면 도시가 수십 개
    # 찍혀 라벨이 뒤죽박죽 겹친다는 피드백(2026-09-17, 사용자 제안 기준값).
    _CITY_COUNT_THRESHOLD_FOR_PROVINCE = 15

    def set_points(self, points: list[tuple[float, float, int, str, str, str]]) -> None:
        """points = [(위도, 경도, 사진 개수, 도시 라벨, 나라코드, 시/도 라벨), ...]."""
        self._raw_points = points
        self._marker_mode = None  # 다음 _rebuild_markers가 무조건 다시 그리게
        if points and not self._data_view_fitted and self.viewport().width() > 0:
            self.zoom_out_to_all()
            self._data_view_fitted = True
            self._centered_once = True  # resizeEvent의 KOREA_CENTER 기본값으로 되돌아가지 않게
        self._rebuild_markers()

    def reset_initial_view(self) -> None:
        """새 스캔 결과가 들어오면(gui/city_organize_screen.py::set_result가
        새 result를 감지했을 때 호출) 이전 데이터에 맞춰 확대해둔 상태를
        잊는다 — 다음 set_points 때 새 데이터 전체가 다시 자동으로 다
        보이게 하기 위함."""
        self._data_view_fitted = False

    def _visible_points(self) -> list[tuple[float, float, int, str, str, str]]:
        visible_scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        return [p for p in self._raw_points if visible_scene_rect.contains(QPointF(p[1], -p[0]))]

    def _decide_marker_mode(self) -> str:
        """화면에 실제로 보이는 점들만 기준으로 판단한다 — 팬/줌으로 보이는
        범위가 좁아지면(도시 하나만 남으면) 전체 데이터가 여러 나라/도시를
        아우르고 있어도 도시 단위로 되돌아가야 하기 때문."""
        visible = self._visible_points()
        if len({p[4] for p in visible}) >= 2:
            return "country"
        if len(visible) > self._CITY_COUNT_THRESHOLD_FOR_PROVINCE:
            return "province"
        return "city"

    def _rebuild_markers(self) -> None:
        """화면에 나라가 2개 이상 보이면 나라 단위로, 한 나라 안에서도 도시가
        너무 많이 보이면(_CITY_COUNT_THRESHOLD_FOR_PROVINCE) 시/도 단위로
        뭉친다 — 여러 도시 이름이 한꺼번에 보이면 빽빽하게 겹쳐 어지럽다는
        피드백(2026-09-17). 그 외엔 지금까지처럼 도시 단위 그대로."""
        mode = self._decide_marker_mode()
        if mode == self._marker_mode:
            self._layout_labels()
            return
        self._marker_mode = mode

        for marker in self._markers:
            self.scene().removeItem(marker)
        self._markers = []
        if not self._raw_points:
            self._layout_labels()
            return

        if mode == "country":
            self._build_aggregated_markers(
                group_key=lambda p: p[4],
                label_for=lambda key: country_name_ko(key),
                color_for=lambda key: _marker_color_for_key(key),
                base_radius=6,
                radius_span=12,
            )
        elif mode == "province":
            self._build_aggregated_markers(
                group_key=lambda p: (p[4], p[5]),
                label_for=lambda key: key[1],
                color_for=lambda key: _marker_color_for_key(key),
                base_radius=5.5,
                radius_span=11,
            )
        else:
            self._build_city_markers()
        self._layout_labels()

    def _build_city_markers(self) -> None:
        max_count = max(p[2] for p in self._raw_points)
        for lat, lon, count, label, _cc, _province in self._raw_points:
            radius = 5 + (count / max_count) * 10
            marker = _CityMarker(radius, f"{label} ({count})", color=_marker_color_for_key(label))
            marker.setPos(lon, -lat)
            self._wire_marker_clicks(marker, [(lat, lon)])
            self.scene().addItem(marker)
            self._markers.append(marker)

    def _build_aggregated_markers(self, *, group_key, label_for, color_for, base_radius: float, radius_span: float) -> None:
        """나라 단위/시·도 단위 마커를 같은 방식으로 만든다 — group_key(점)가
        그룹 식별자(나라 코드, 또는 (나라코드, 시/도) 쌍)를 돌려주고,
        label_for(식별자)가 화면에 보일 이름을, color_for(식별자)가 핀 색을
        돌려준다. 위치는 그룹 안 도시들의 사진 수 가중 평균(사진이 많은
        쪽으로 치우침) — 행정구역의 지리적 중심이 아니라 "실제 사진이 몰린
        자리"에 찍히게 하기 위함."""
        groups: dict = {}
        for lat, lon, count, _label, cc, province in self._raw_points:
            key = group_key((lat, lon, count, _label, cc, province))
            groups.setdefault(key, []).append((lat, lon, count))

        aggregated = []
        for key, entries in groups.items():
            total = sum(e[2] for e in entries)
            avg_lat = sum(e[0] * e[2] for e in entries) / total
            avg_lon = sum(e[1] * e[2] for e in entries) / total
            member_points = [(e[0], e[1]) for e in entries]
            aggregated.append((avg_lat, avg_lon, total, label_for(key), color_for(key), member_points))

        max_count = max(a[2] for a in aggregated)
        for lat, lon, count, name, color, member_points in aggregated:
            radius = base_radius + (count / max_count) * radius_span
            marker = _CityMarker(radius, f"{name} ({count})", color=color)
            marker.setPos(lon, -lat)
            self._wire_marker_clicks(marker, member_points)
            self.scene().addItem(marker)
            self._markers.append(marker)

    def _wire_marker_clicks(self, marker: "_CityMarker", member_points: list[tuple[float, float]]) -> None:
        """좌클릭(그 마커가 대표하는 지점들이 화면에 꽉 차게 확대 — "핀
        열기") / 우클릭("축소해서 전체 보기" 메뉴 — "핀 닫기") 둘 다 연결한다
        (2026-09-17, 사용자 요청). 도시 단위 마커는 지점이 하나뿐이라
        _fit_scene_rect의 최소 확대 범위(min_span)가 대신 적용된다."""
        extent = self._points_bounds(member_points)
        marker.on_left_click = lambda extent=extent: self._fit_scene_rect(QRectF(extent))
        marker.on_right_click = lambda screen_pos: self._show_marker_context_menu(screen_pos)

    def _show_marker_context_menu(self, screen_pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        zoom_out_action = menu.addAction("축소해서 전체 보기")
        chosen = menu.exec(screen_pos.toPoint() if hasattr(screen_pos, "toPoint") else screen_pos)
        if chosen is zoom_out_action:
            self.zoom_out_to_all()

    def _layout_labels(self) -> None:
        """줌/팬으로 도시 점들의 화면 위치가 바뀔 때마다, 라벨끼리 겹치지
        않도록 각 마커의 라벨을 위/아래로 밀어낸다(점 위치 자체는 그대로).
        사진이 많은(원이 큰) 도시부터 우선 배치해서 더 눈에 띄는 도시가
        원래 자리(오프셋 0)를 먼저 차지하게 한다."""
        if not self._markers:
            return

        fm = QFontMetrics(self.font())
        placed_rects: list[QRectF] = []
        candidates = [0, 16, -16, 32, -32, 48, -48, 64, -64]

        for marker in sorted(self._markers, key=lambda m: -m.radius()):
            screen_pos = self.mapFromScene(marker.pos())
            text_width = fm.horizontalAdvance(marker.label_text())
            text_height = fm.height()
            base_x = screen_pos.x() + marker.radius() + 4

            chosen_dy = candidates[0]
            for dy in candidates:
                rect = QRectF(base_x, screen_pos.y() + dy - text_height + 2, text_width, text_height)
                if not any(rect.intersects(other) for other in placed_rects):
                    chosen_dy = dy
                    placed_rects.append(rect)
                    break
            else:
                # 다 겹치면(도시가 아주 빽빽하면) 그냥 기본 위치라도 보여준다 —
                # 무한정 밀어내지 않는다.
                placed_rects.append(
                    QRectF(base_x, screen_pos.y() + candidates[0] - text_height + 2, text_width, text_height)
                )

            marker.set_label_dy(chosen_dy)

    def _update_country_label_visibility(self) -> None:
        """나라가 화면에서 차지하는 크기(그 나라 최대 땅덩어리의 위경도
        바운딩박스를 화면 좌표로 투영한 크기)가 일정 이상일 때만 이름을
        보여준다 — 세계 전체를 보면 큰 나라만, 확대할수록 작은 나라까지.

        먼저 그 나라가 지금 보이는 범위 안에 실제로 들어와 있는지부터
        확인해야 한다 — 안 그러면 화면 밖 먼 나라도(예: 한국을 확대했을 때
        저 멀리 있는 베트남) 그 나라 자체 크기가 크다는 이유만으로 "크게
        보인다"고 착각해 라벨이 뜨는 버그가 있었다(실측으로 발견).

        나라 단위로 뭉친 마커(_build_country_markers)를 보여주는 중일 땐
        마커 라벨에 이미 나라 이름이 있으니, 배경의 이탤릭 나라 이름까지
        같이 뜨면 같은 정보가 겹쳐 보인다 — 그 동안은 전부 숨긴다."""
        if self._marker_mode == "country":
            for label_item, _, _ in self._country_anchors:
                label_item.setVisible(False)
            return
        visible_scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        for label_item, _, bbox in self._country_anchors:
            # bbox는 (경도, 위도) 기준 — 씬 좌표계(경도, -위도)로 바꿔서 비교.
            scene_bbox = QRectF(bbox.left(), -bbox.bottom(), bbox.width(), bbox.height())
            if not scene_bbox.intersects(visible_scene_rect):
                label_item.setVisible(False)
                continue

            top_left = self.mapFromScene(bbox.left(), -bbox.bottom())
            bottom_right = self.mapFromScene(bbox.right(), -bbox.top())
            width = abs(bottom_right.x() - top_left.x())
            height = abs(bottom_right.y() - top_left.y())
            label_item.setVisible(width >= _COUNTRY_LABEL_MIN_PX or height >= _COUNTRY_LABEL_MIN_PX)

    def center_on(self, lat: float, lon: float, span_deg: float = 14.0) -> None:
        rect = QRectF(lon - span_deg, -(lat + span_deg / 2), span_deg * 2, span_deg)
        self._fit_scene_rect(rect)

    def focus_on_locations(self, locations: list[tuple[float, float]]) -> None:
        """gui/city_organize_screen.py의 도시 카드 헤더를 눌러 펼칠 때처럼,
        지도 바깥(목록)에서 "이 지점들 쪽으로 이동해줘"라고 요청할 때 쓰는
        공개 API — 핀 클릭("열기")이 쓰는 것과 같은 _fit_scene_rect를
        재사용한다(2026-09-18, 사용자 요청: "마카오 선택하면 마카오로
        지도를 움직였으면 좋겠는데")."""
        if not locations:
            return
        self._fit_scene_rect(self._points_bounds(locations))

    def _fit_scene_rect(self, rect: QRectF) -> None:
        """주어진 씬 좌표 범위(경도, -위도 기준)가 화면에 꽉 차게 확대/이동한다
        — center_on(초기 중심 이동)과 핀 클릭("열기")/우클릭("닫기")가 공유하는
        실제 줌 동작. 범위가 점 하나뿐이라 폭/높이가 0이면 fitInView가 무한
        배율로 확대하려 들어 _MAX_SCALE을 넘어버리므로, 최소 크기를 보장한다.

        transformationAnchor가 AnchorUnderMouse(휠 줌이 마우스 위치를 고정점
        삼게 하려고 켜둠)인 채로 fitInView를 부르면, fitInView 내부의 scale()
        호출도 "지금 마우스 커서 위치"를 고정점으로 잡아버려서 핀을 클릭한
        위치 쪽으로 확대 결과가 엉뚱하게 쏠린다(2026-09-17, 핀 클릭 기능 추가
        중 실측으로 발견 — 화면이 목표 지점이 아니라 태평양 한가운데를 보여줌).
        이 메서드가 하는 프로그램적 이동/확대는 항상 뷰 중앙을 기준으로 삼아야
        하므로, 그동안만 AnchorViewCenter로 바꿔둔다."""
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        min_span = 0.05
        if rect.width() < min_span:
            rect.adjust(-(min_span - rect.width()) / 2, 0, (min_span - rect.width()) / 2, 0)
        if rect.height() < min_span:
            rect.adjust(0, -(min_span - rect.height()) / 2, 0, (min_span - rect.height()) / 2)
        self.resetTransform()
        self.fitInView(rect, Qt.KeepAspectRatio)
        # 확대 직후 너무 빡빡하게 붙지 않도록 살짝 더 축소(20% 여백).
        self.scale(1 / 1.2, 1 / 1.2)
        # _zoom_by(휠/버튼 줌)는 _MIN_SCALE/_MAX_SCALE을 넘는 배율 자체를
        # 거부해서 절대 못 넘어가지만, fitInView는 rect 크기에 맞춰 배율을
        # 자동 계산하므로 같은 보장이 없다 — 핀 하나만 있는 도시를 클릭하면
        # min_span=0.05짜리 좁은 rect가 되어 이 캡 없이는 시/도보다 훨씬
        # 깊이 확대돼버렸다(2026-09-18, "확대는 제한을 좀 하자 시/도 이상은
        # 더 확대 못하게 해줘"). fitInView 직후 실제 배율을 읽어 캡 안으로
        # 다시 눌러준다.
        current_scale = self.transform().m11()
        if current_scale > self._MAX_SCALE:
            self.scale(self._MAX_SCALE / current_scale, self._MAX_SCALE / current_scale)
        elif current_scale < self._MIN_SCALE:
            self.scale(self._MIN_SCALE / current_scale, self._MIN_SCALE / current_scale)
        self.setTransformationAnchor(anchor)  # 휠 줌 등 평소 동작을 위해 원래대로 복구
        self.view_changed.emit()

    def _points_bounds(self, points) -> QRectF:
        """points(위도, 경도, ...) 목록의 씬 좌표(경도, -위도) 바운딩박스."""
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        return QRectF(min(lons), -max(lats), max(lons) - min(lons), max(lats) - min(lats))

    def zoom_out_to_all(self) -> None:
        """핀 우클릭 "축소해서 보기" — 특정 지역이 아니라 전체 데이터가 다시
        다 보이게 되돌린다(팬/줌 히스토리를 따로 안 쌓아서, "한 단계 전으로"
        대신 "처음부터 전체 보기"로 단순화— 2026-09-17, 사용자 확인)."""
        if not self._raw_points:
            return
        bounds = self._points_bounds(self._raw_points)
        # 가장자리에 걸친 점이 "화면 밖"으로 판정돼(부동소수점 경계 오차)
        # 방금 뭉쳐서 봐야 할 점이 빠진 채로 모드가 재계산되는 걸 막기 위해
        # 여유를 넉넉히 둔다 — _fit_scene_rect 자체의 20% 축소만으론 이
        # 경계 케이스에 충분하지 않았다(실측으로 확인).
        margin_x = max(bounds.width() * 0.15, 0.02)
        margin_y = max(bounds.height() * 0.15, 0.02)
        bounds.adjust(-margin_x, -margin_y, margin_x, margin_y)
        self._fit_scene_rect(bounds)

    def visible_bounds(self) -> tuple[float, float, float, float]:
        """현재 화면에 보이는 (lat_min, lat_max, lon_min, lon_max)."""
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        return -rect.bottom(), -rect.top(), rect.left(), rect.right()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            # 일부 트랙패드/드라이버는 angleDelta 대신 pixelDelta만 보낸다
            # (Windows Precision Touchpad 등) — 그 경우 확대/축소가 아예
            # 반응 없는 것처럼 보였다(실사용 피드백으로 발견).
            delta = event.pixelDelta().y()
        if delta == 0:
            return
        self._zoom_by(1.2 if delta > 0 else 1 / 1.2)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._start_view_changed_timer()

    @staticmethod
    def _event_pos(event):
        return event.position().toPoint() if hasattr(event, "position") else event.pos()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._marker_press_pos = self._event_pos(event)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        # 핀 클릭("열기") 판정 — _CityMarker가 마우스 버튼을 아예 안 받게
        # 했으므로(setAcceptedMouseButtons(Qt.NoButton), 안 그러면 핀 위에서
        # 시작한 드래그가 패닝되지 않는 문제가 있었다 — 2026-09-17, 사용자
        # 리포트) press/release가 항상 여기(뷰)로 온다. 눌렀다 뗀 위치가 몇
        # 픽셀 이내면 클릭, 그보다 많이 움직였으면 드래그(패닝)로 보고 아무
        # 것도 안 한다.
        pos = self._event_pos(event)
        if event.button() == Qt.LeftButton and self._marker_press_pos is not None:
            moved = (pos - self._marker_press_pos).manhattanLength()
            if moved <= 4:
                item = self.itemAt(pos)
                if isinstance(item, _CityMarker) and item.on_left_click is not None:
                    item.on_left_click()
            self._marker_press_pos = None

    def _start_view_changed_timer(self) -> None:
        # QGraphicsScene에 국가 경계를 채우는 동안이나(생성자), 위젯이
        # 정리되는 동안(소멸자 직전) Qt가 파이썬 쪽 속성이 아직 없거나 이미
        # 지워진 시점에도 scrollContentsBy를 부를 수 있다 — PySide6가 가상
        # 메서드 오버라이드를 C++ 쪽 생명주기에 맞춰 부르기 때문(2026-09-17,
        # 테스트 중 AttributeError로 재현). 이 시점의 view_changed는 의미가
        # 없으니 조용히 무시한다.
        timer = getattr(self, "_view_changed_timer", None)
        if timer is not None:
            timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._centered_once:
            self._centered_once = True
            # set_points가 데이터를 이미 들고 있었는데 그때는 뷰포트 크기가
            # 아직 0이라 zoom_out_to_all을 못 했던 경우(위젯이 보이기 전에
            # 스캔 결과가 먼저 들어온 경우) — 지금 크기가 잡혔으니 여기서
            # 마저 맞춘다. 데이터가 아직 없으면(스캔 전) 기존처럼 한국
            # 언저리를 기본값으로 보여준다.
            if self._raw_points:
                self.zoom_out_to_all()
                self._data_view_fitted = True
            else:
                self.center_on(*KOREA_CENTER)
        else:
            self._update_country_label_visibility()
        overlay = getattr(self, "_overlay_toolbar", None)
        if overlay is not None:
            self._position_overlay_toolbar()
