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

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

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
_MARKER_COLOR = QColor(218, 90, 90, 210)  # theme.py COLORS['danger']에 알파 추가

# 나라 이름 라벨을 보여줄 최소 화면 크기(px) — 이보다 작게 보이면(세계 전체를
# 보는 중이라 그 나라가 작게 찍히면) 숨긴다. 확대할수록 큰 나라부터, 더
# 확대하면 작은 나라까지 순서대로 나타난다.
_COUNTRY_LABEL_MIN_PX = 50


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

    def __init__(self, radius: float, label: str):
        super().__init__()
        self._radius = radius
        self._label = label
        self._label_dy = 0.0
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(10)

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

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_MARKER_COLOR)
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
    _MAX_SCALE = 6000.0  # 도시 안쪽까지 확대 가능한 수준

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
        self.view_changed.connect(self._rebuild_markers)
        self.view_changed.connect(self._update_country_label_visibility)

        # 드래그로 팬 하는 동안 scrollContentsBy가 픽셀 단위로 계속 불려서
        # view_changed도 그만큼 자주(초당 수십 번) 발생한다 — 도시가 수십 개
        # (실사용 4만 6천 장 규모 리포트)면 _rebuild_markers/_layout_labels가
        # 매번 그 전부를 다시 계산해서 드래그 중 응답 없음처럼 보였다
        # (2026-09-17, 사용자 리포트). gui/image_viewer.py::_refit_timer와
        # 같은 이유로, 실제 재계산은 마지막 이벤트 뒤 잠깐(디바운스) 멈췄을
        # 때만 한다 — wheelEvent/scrollContentsBy가 직접 view_changed를
        # emit하지 않고 이 타이머를 재시작하도록 바꿨다(아래 참고).
        self._view_changed_timer = QTimer(self)
        self._view_changed_timer.setSingleShot(True)
        self._view_changed_timer.setInterval(120)
        self._view_changed_timer.timeout.connect(self.view_changed.emit)

    def set_points(self, points: list[tuple[float, float, int, str, str]]) -> None:
        """points = [(위도, 경도, 사진 개수, 라벨, 나라코드), ...]."""
        self._raw_points = points
        self._marker_mode = None  # 다음 _rebuild_markers가 무조건 다시 그리게
        self._rebuild_markers()

    def _distinct_visible_countries(self) -> set[str]:
        visible_scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        return {
            cc
            for lat, lon, _count, _label, cc in self._raw_points
            if visible_scene_rect.contains(QPointF(lon, -lat))
        }

    def _rebuild_markers(self) -> None:
        """화면에 나라가 2개 이상 보이면 도시 마커 대신 나라 단위로 뭉친
        마커를 보여준다 — 여러 나라의 도시가 한꺼번에 보이면 이름이 빽빽하게
        겹쳐 어지럽다는 피드백(2026-09-17). 나라가 1개(또는 GPS가 아예 하나도
        안 보임)면 지금까지처럼 도시 단위 그대로."""
        mode = "country" if len(self._distinct_visible_countries()) >= 2 else "city"
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
            self._build_country_markers()
        else:
            self._build_city_markers()
        self._layout_labels()

    def _build_city_markers(self) -> None:
        max_count = max(p[2] for p in self._raw_points)
        for lat, lon, count, label, _cc in self._raw_points:
            radius = 5 + (count / max_count) * 10
            marker = _CityMarker(radius, f"{label} ({count})")
            marker.setPos(lon, -lat)
            self.scene().addItem(marker)
            self._markers.append(marker)

    def _build_country_markers(self) -> None:
        """나라별로 사진 개수를 합치고, 위치는 그 나라 안 도시들의 가중
        평균(사진 많은 도시 쪽으로 치우침)으로 잡는다 — 나라의 지리적 중심이
        아니라 "실제 사진이 몰린 자리"에 마커가 찍히게 하기 위함(예: 일본
        전체 중심이 아니라 도쿄/오사카 근처)."""
        by_country: dict[str, list[tuple[float, float, int]]] = {}
        for lat, lon, count, _label, cc in self._raw_points:
            by_country.setdefault(cc, []).append((lat, lon, count))

        aggregated = []
        for cc, entries in by_country.items():
            total = sum(e[2] for e in entries)
            avg_lat = sum(e[0] * e[2] for e in entries) / total
            avg_lon = sum(e[1] * e[2] for e in entries) / total
            aggregated.append((avg_lat, avg_lon, total, country_name_ko(cc)))

        max_count = max(a[2] for a in aggregated)
        for lat, lon, count, name in aggregated:
            radius = 6 + (count / max_count) * 12
            marker = _CityMarker(radius, f"{name} ({count})")
            marker.setPos(lon, -lat)
            self.scene().addItem(marker)
            self._markers.append(marker)

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
        self.resetTransform()
        self.fitInView(rect, Qt.KeepAspectRatio)
        self.view_changed.emit()

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
        factor = 1.2 if delta > 0 else 1 / 1.2
        new_scale = self.transform().m11() * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self.scale(factor, factor)
            self._view_changed_timer.start()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._view_changed_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._centered_once:
            self._centered_once = True
            self.center_on(*KOREA_CENTER)
        else:
            self._update_country_label_visibility()
