"""
experiments/city_organize_prototype/app.py

"도시별 정리" 프로토타입 — 본체에 엮기 전에 확인해야 할 것들을 검증한다:
1. EXIF GPSInfo에서 위경도를 뽑아내는 게(core/analyzer.py의 DateTimeOriginal
   처리와 같은 get_ifd() 패턴) 실제로 되는지.
2. reverse_geocoder(오프라인, 인터넷 불필요)로 위경도 -> 도시명 매칭이 되는지,
   그리고 속도가 실사용 규모(수천~수만 장)에서 괜찮은지.
3. PHASE2_사진정리_기획.md "위치 시각화(지도)" 절 — 도시를 점으로 찍은
   세계 지도. 육지 경계는 land110.json(Natural Earth 1:110m, 퍼블릭 도메인 —
   topojson/world-atlas가 TopoJSON으로 재배포, ISC 유사 라이선스)를
   topojson_decode.py로 직접 디코딩해서 그린다. 최초 기획은 "확대·이동 없는
   고정 지도"였지만, 실사용 확인 중 "한국 위주로 보여주고 확대/축소가
   됐으면 좋겠다"는 피드백을 받아 QGraphicsView 기반 줌/팬으로 바꿨다
   (gui/image_viewer.py의 _ZoomPanView와 같은 패턴 — 이 프로토타입은 메인
   앱과 별도 venv라 직접 import는 못 하고 같은 방식을 그대로 재구현).
4. 지도에서 확대한 범위 안의 사진만 아래 목록에 보여주고(팬/줌할 때마다
   갱신), 목록에서 사진을 고르면 "뷰어 + 하단 썸네일 목록" 화면으로
   전환한다(gui/date_group_detail_screen.py와 같은 레이아웃 원칙).

메인 앱과 완전히 분리된 별도 .venv에서만 돈다(PySide6/Pillow도 이 venv에 따로
설치) — 검증 전까지 본체 requirements.txt에는 아무것도 추가하지 않는다.

개인정보 원칙: 위경도/도시명은 이 프로세스 밖으로 절대 나가지 않는다(네트워크
호출 없음 — reverse_geocoder는 패키지에 내장된 도시 좌표 CSV로만 찾는다).
"""

from __future__ import annotations

import io
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import piexif
from PIL import ExifTags, Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from topojson_decode import load_land_polygons

_LAND_TOPOJSON_PATH = Path(__file__).resolve().parent / "land110.json"
_KOREA_CENTER = (36.5, 127.8)  # 초기 지도 중심(대략 대한민국 중앙)

# --- 실측 지점(랜드마크) — 실제 사진에 GPS EXIF가 없어서, 알려진 좌표로
# 합성 JPEG을 만들어 "GPS 추출 -> 도시 매칭" 파이프라인 전체를 검증한다. ---
_SAMPLE_POINTS = [
    ("seoul.jpg", 37.5665, 126.9780, "서울 시청 부근"),
    ("tokyo.jpg", 35.6762, 139.6503, "도쿄역 부근"),
    ("newyork.jpg", 40.7128, -74.0060, "뉴욕 시청 부근"),
    ("paris.jpg", 48.8566, 2.3522, "파리 시청 부근"),
    ("busan.jpg", 35.1796, 129.0756, "부산 시청 부근"),
    ("jeju.jpg", 33.4996, 126.5312, "제주 시청 부근"),
    ("no_gps.jpg", None, None, "GPS 정보 없음(합성 사진에 GPS 태그를 안 넣음)"),
]


def _to_dms_rational(value: float) -> tuple:
    """십진 좌표 -> EXIF가 요구하는 (도, 분, 초) 분수 튜플. 실제 카메라가
    기록하는 형식과 동일 — 이걸 다시 읽어서 십진수로 복원하는 코드(추출 함수)를
    검증하기 위한 왕복 테스트용."""
    value = abs(value)
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 100)
    return ((degrees, 1), (minutes, 1), (seconds, 100))


def make_sample_photo(path: Path, lat: Optional[float], lon: Optional[float]) -> None:
    """단색 JPEG 한 장을 만들고, lat/lon이 있으면 실제 카메라와 같은 형식의
    GPSInfo EXIF를 심는다(piexif로 작성 — 실제 서비스 코드에서는 안 쓰고,
    이 프로토타입의 "가짜 GPS 사진" 준비용으로만 사용)."""
    img = Image.new("RGB", (320, 240), (120, 160, 200))
    if lat is None:
        img.save(path, "jpeg")
        return

    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: _to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: "E" if lon >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: _to_dms_rational(lon),
    }
    exif_bytes = piexif.dump({"GPS": gps_ifd})
    buf = io.BytesIO()
    img.save(buf, "jpeg")
    buf.seek(0)
    img2 = Image.open(buf)
    img2.save(path, "jpeg", exif=exif_bytes)


def _dms_to_decimal(dms, ref: str) -> float:
    """Pillow의 exif.get_ifd(GPSInfo)는 (분자, 분모) 유리수 쌍이 아니라 이미
    계산된 (도, 분, 초) 실수 3개를 그대로 준다(piexif.load()의 원시 유리수
    형식과 다름 — 처음에 이걸 착각해서 전부 None이 나왔었다)."""
    degrees, minutes, seconds = dms
    value = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        value = -value
    return value


def extract_gps(path: str) -> Optional[tuple[float, float]]:
    """core/analyzer.py::_extract_captured_at와 완전히 같은 패턴 — Pillow의
    Image.getexif()는 최상위 IFD0만 평평하게 주므로, GPSInfo 서브 IFD는
    get_ifd(ExifTags.IFD.GPSInfo)로 따로 꺼내야 한다."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_ifd:
                return None

            lat_dms = gps_ifd.get(2)  # GPSLatitude
            lat_ref = gps_ifd.get(1)  # GPSLatitudeRef
            lon_dms = gps_ifd.get(4)  # GPSLongitude
            lon_ref = gps_ifd.get(3)  # GPSLongitudeRef
            if not (lat_dms and lat_ref and lon_dms and lon_ref):
                return None

            lat = _dms_to_decimal(lat_dms, lat_ref)
            lon = _dms_to_decimal(lon_dms, lon_ref)
            return (lat, lon)
    except Exception:
        return None


@dataclass
class PhotoRow:
    path: str
    note: str
    gps: Optional[tuple[float, float]]
    city: Optional[str]
    city_center: Optional[tuple[float, float]] = None  # 지도에 찍을 도시 대표 좌표(reverse_geocoder가 준 값)

    def map_point(self) -> Optional[tuple[float, float]]:
        """지도/영역 필터링에 쓸 좌표 — 사진 자체 GPS가 있으면 그걸, 없으면
        매칭된 도시 중심 좌표로 대신한다."""
        return self.gps or self.city_center


def build_rows(sample_dir: Path) -> list[PhotoRow]:
    import reverse_geocoder as rg

    rows: list[PhotoRow] = []
    coords_needed: list[tuple[int, float, float]] = []

    for filename, lat, lon, note in _SAMPLE_POINTS:
        path = sample_dir / filename
        make_sample_photo(path, lat, lon)
        extracted = extract_gps(str(path))
        rows.append(PhotoRow(path=str(path), note=note, gps=extracted, city=None))
        if extracted is not None:
            coords_needed.append((len(rows) - 1, *extracted))

    if coords_needed:
        t0 = time.time()
        results = rg.search([(c[1], c[2]) for c in coords_needed], mode=1)
        elapsed = time.time() - t0
        print(f"reverse_geocoder.search({len(coords_needed)}개): {elapsed:.3f}초")
        for (idx, _, _), r in zip(coords_needed, results):
            rows[idx].city = f"{r['name']}, {r['cc']}"
            rows[idx].city_center = (float(r["lat"]), float(r["lon"]))

    return rows


def rows_for_real_photos(paths: list[str]) -> list[PhotoRow]:
    """실제 사진 파일들의 GPS를 읽어 도시를 매칭한다 — 합성 랜드마크 좌표와
    달리 진짜 카메라/폰이 기록한 EXIF라 형식이 지저분할 수 있어(제조사별
    차이, 정밀도 등) 실제 검증에 의미가 있다."""
    import reverse_geocoder as rg

    rows: list[PhotoRow] = []
    coords_needed: list[tuple[int, float, float]] = []
    for path in paths:
        gps = extract_gps(path)
        rows.append(PhotoRow(path=path, note="직접 선택한 사진", gps=gps, city=None))
        if gps is not None:
            coords_needed.append((len(rows) - 1, *gps))

    if coords_needed:
        results = rg.search([(c[1], c[2]) for c in coords_needed], mode=1)
        for (idx, _, _), r in zip(coords_needed, results):
            rows[idx].city = f"{r['name']}, {r['cc']}"
            rows[idx].city_center = (float(r["lat"]), float(r["lon"]))

    return rows


class _CityMarker(QGraphicsItem):
    """지도 위 도시 점 하나 — 원 + 라벨. ItemIgnoresTransformations를 켜서
    지도를 확대/축소해도 화면상 크기(점, 글자)는 항상 일정하게 유지된다
    (좌표만 지도 줌/팬을 따라간다). QGraphicsEllipseItem + 별도 텍스트
    아이템 두 개로 만들면 라벨 오프셋이 줌 배율에 따라 어긋나서, 원과
    라벨을 한 아이템 안에서 같이 그린다."""

    def __init__(self, radius: float, label: str):
        super().__init__()
        self._radius = radius
        self._label = label
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return QRectF(-self._radius, -self._radius, self._radius * 2 + 160, self._radius * 2 + 4)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(220, 60, 60, 210))
        painter.drawEllipse(QPointF(0, 0), self._radius, self._radius)
        painter.setPen(QColor("#222"))
        painter.drawText(QPointF(self._radius + 4, 4), self._label)


class CityMapView(QGraphicsView):
    """줌(휠)·팬(드래그)이 되는 세계 지도. 씬 좌표계 = 경위도 그대로
    (x=경도, y=-위도 — Qt는 y가 아래로 갈수록 커지므로 북쪽이 위로 오게
    부호를 뒤집는다). gui/image_viewer.py::_ZoomPanView와 같은 원리."""

    view_changed = Signal()  # 줌/팬이 끝날 때마다(방문 범위가 바뀔 때마다) 발생

    _MIN_SCALE = 1.5   # 세계 전체가 겨우 들어오는 수준
    _MAX_SCALE = 6000.0  # 도시 안쪽까지 확대 가능한 수준

    def __init__(self, parent=None):
        scene = QGraphicsScene(-180, -90, 360, 180)
        # PySide6에서는 뷰가 씬의 소유권을 가져가지 않는다 — self._scene으로
        # 파이썬 참조를 안 잡아두면 __init__ 종료 직후 GC가 씬을 회수해버려서
        # self.scene()이 조용히 None이 된다(실제로 이 버그로 한 번 깨짐).
        self._scene = scene
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scene.setBackgroundBrush(QColor("#dbe9f4"))  # 바다

        try:
            land_rings = load_land_polygons(str(_LAND_TOPOJSON_PATH))
        except Exception as exc:
            print("육지 데이터 로드 실패:", exc)
            land_rings = []

        land_path = QPainterPath()
        for ring in land_rings:
            if len(ring) < 3:
                continue
            sub = QPainterPath()
            sub.moveTo(ring[0][0], -ring[0][1])
            for lon, lat in ring[1:]:
                sub.lineTo(lon, -lat)
            sub.closeSubpath()
            land_path.addPath(sub)
        scene.addPath(land_path, QPen(QColor("#9fb89f"), 0.05), QColor("#c9dfc9"))

        self._markers: list[_CityMarker] = []
        self._centered_once = False

    def set_points(self, points: list[tuple[float, float, int, str]]) -> None:
        for marker in self._markers:
            self.scene().removeItem(marker)
        self._markers = []
        if not points:
            return
        max_count = max(p[2] for p in points)
        for lat, lon, count, label in points:
            radius = 5 + (count / max_count) * 10
            marker = _CityMarker(radius, f"{label} ({count})")
            marker.setPos(lon, -lat)
            self.scene().addItem(marker)
            self._markers.append(marker)

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
            # 반응 없는 것처럼 보였다.
            delta = event.pixelDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else 1 / 1.2
        new_scale = self.transform().m11() * factor
        if self._MIN_SCALE <= new_scale <= self._MAX_SCALE:
            self.scale(factor, factor)
            self.view_changed.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.view_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._centered_once:
            self._centered_once = True
            self.center_on(*_KOREA_CENTER)


def _load_scaled_pixmap(path: str, box: int) -> Optional[QPixmap]:
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    return pixmap.scaled(box, box, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class PhotoDetailPage(QWidget):
    """지도 아래 목록에서 사진을 고르면 여는 화면 — 위: 큰 미리보기,
    아래: 같은 목록(현재 지도 범위 안 사진들) 썸네일 줄. 클릭하면 위
    미리보기만 바뀐다(gui/date_group_detail_screen.py와 같은 레이아웃
    원칙 — 실제 확대/회전 뷰어는 메인 앱의 gui/image_viewer.py에서 이미
    검증됐으므로 여기서는 단순 미리보기로 레이아웃 흐름만 확인한다)."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        back_btn = QPushButton("← 지도로")
        back_btn.clicked.connect(self.back_requested.emit)
        top_row.addWidget(back_btn)
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: 700;")
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(360, 300)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #eee; border-radius: 8px;")
        layout.addWidget(self.preview_label, alignment=Qt.AlignHCenter)

        self.strip_layout = QHBoxLayout()
        strip_container = QWidget()
        strip_container.setLayout(self.strip_layout)
        layout.addWidget(strip_container)
        layout.addStretch(1)

        self._rows: list[PhotoRow] = []

    def set_rows(self, rows: list[PhotoRow], selected: PhotoRow) -> None:
        self._rows = rows
        while self.strip_layout.count():
            item = self.strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row in rows:
            thumb = QLabel()
            thumb.setFixedSize(72, 72)
            thumb.setAlignment(Qt.AlignCenter)
            pixmap = _load_scaled_pixmap(row.path, 72)
            if pixmap is not None:
                thumb.setPixmap(pixmap)
            thumb.setStyleSheet(
                "border: 2px solid #4a90d9; border-radius: 6px;"
                if row is selected
                else "border: 2px solid transparent;"
            )
            thumb.setCursor(Qt.PointingHandCursor)
            thumb.mousePressEvent = lambda _e, r=row: self._select(r)
            self.strip_layout.addWidget(thumb)
        self.strip_layout.addStretch(1)

        self._select(selected)

    def _select(self, row: PhotoRow) -> None:
        pixmap = _load_scaled_pixmap(row.path, 340)
        if pixmap is not None:
            self.preview_label.setPixmap(pixmap)
        else:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("미리보기를 생성할 수 없습니다.")
        self.title_label.setText(f"{Path(row.path).name} — {row.city or '위치 정보 없음'} · {row.note}")
        for i in range(self.strip_layout.count() - 1):  # 마지막은 stretch
            widget = self.strip_layout.itemAt(i).widget()
            if widget is not None:
                is_selected = self._rows[i] is row
                widget.setStyleSheet(
                    "border: 2px solid #4a90d9; border-radius: 6px;"
                    if is_selected
                    else "border: 2px solid transparent;"
                )


class MapPage(QWidget):
    """지도 + "이 범위 안의 사진" 목록. 지도를 확대/이동할 때마다 목록이
    현재 보이는 위경도 범위 안의 사진으로만 갱신된다(2026-09-07, 사용자
    요청)."""

    photo_selected = Signal(object, list)  # (선택한 PhotoRow, 같은 범위의 PhotoRow 목록)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[PhotoRow] = []

        layout = QVBoxLayout(self)
        self.map_view = CityMapView()
        layout.addWidget(self.map_view, stretch=1)

        region_label = QLabel("이 범위 안의 사진")
        region_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(region_label)

        self.region_list = QListWidget()
        self.region_list.setMaximumHeight(160)
        self.region_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.region_list)

        self.map_view.view_changed.connect(self._refresh_region_list)

    def set_rows(self, rows: list[PhotoRow], map_points: list[tuple[float, float, int, str]]) -> None:
        self._rows = rows
        self.map_view.set_points(map_points)
        self._refresh_region_list()

    def _rows_in_view(self) -> list[PhotoRow]:
        lat_min, lat_max, lon_min, lon_max = self.map_view.visible_bounds()
        result = []
        for row in self._rows:
            point = row.map_point()
            if point is None:
                continue
            lat, lon = point
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                result.append(row)
        return result

    def _refresh_region_list(self) -> None:
        visible_rows = self._rows_in_view()
        self.region_list.clear()
        for row in visible_rows:
            item = QListWidgetItem(f"{Path(row.path).name} — {row.city or '위치 정보 없음'}")
            item.setData(Qt.UserRole, row)
            self.region_list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.UserRole)
        self.photo_selected.emit(row, self._rows_in_view())


class PrototypeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("도시별 정리 프로토타입 — 메인 앱과 분리된 실험용 도구")
        self.resize(720, 820)

        outer = QVBoxLayout(self)
        title = QLabel("도시별 정리 프로토타입")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        outer.addWidget(title)

        note = QLabel(
            "지도는 한국 중심으로 시작하고, 휠로 확대/축소·드래그로 이동됩니다.\n"
            "확대한 범위 안의 사진만 아래 목록에 뜨고, 목록에서 고르면 뷰어 화면으로 전환돼요.\n"
            "네트워크 호출 없음 — 전부 이 PC 안에서만 계산됩니다."
        )
        note.setStyleSheet("color: #666; font-size: 11px;")
        outer.addWidget(note)

        self.status_label = QLabel("불러오는 중...")
        outer.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        open_btn = QPushButton("실제 사진 열기...")
        open_btn.setToolTip("내 컴퓨터의 진짜 사진을 골라서 GPS -> 도시 매칭이 맞는지 확인합니다.")
        open_btn.clicked.connect(self._on_open_real_photos)
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        rerun_btn = QPushButton("합성 샘플 다시 실행")
        rerun_btn.clicked.connect(self.run)
        btn_row.addWidget(rerun_btn)
        outer.addLayout(btn_row)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, stretch=1)

        self.map_page = MapPage()
        self.map_page.photo_selected.connect(self._open_detail)
        self.stack.addWidget(self.map_page)

        self.detail_page = PhotoDetailPage()
        self.detail_page.back_requested.connect(lambda: self.stack.setCurrentWidget(self.map_page))
        self.stack.addWidget(self.detail_page)

        self._real_rows: list[PhotoRow] = []
        self.run()

    def _open_detail(self, row: PhotoRow, rows_in_view: list) -> None:
        self.detail_page.set_rows(rows_in_view, row)
        self.stack.setCurrentWidget(self.detail_page)

    def _on_open_real_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "GPS 확인할 사진 선택", "", "이미지 (*.jpg *.jpeg *.png *.heic *.heif)"
        )
        if not paths:
            return
        self._real_rows.extend(rows_for_real_photos(paths))
        self.run()

    def run(self):
        sample_dir = Path(__file__).resolve().parent / "sample_photos"
        sample_dir.mkdir(exist_ok=True)

        t0 = time.time()
        rows = build_rows(sample_dir) + self._real_rows
        elapsed = time.time() - t0

        by_city: dict[str, list[PhotoRow]] = {}
        for row in rows:
            key = row.city or "위치 정보 없음"
            by_city.setdefault(key, []).append(row)

        map_points = [
            (city_rows[0].city_center[0], city_rows[0].city_center[1], len(city_rows), city)
            for city, city_rows in by_city.items()
            if city_rows[0].city_center is not None
        ]
        self.map_page.set_rows(rows, map_points)

        self.status_label.setText(
            f"총 {len(rows)}장 처리({len(self._real_rows)}장은 직접 선택), {elapsed*1000:.1f}ms "
            "(첫 실행은 reverse_geocoder 인덱스 로드 포함 더 걸림)"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PrototypeWindow()
    win.show()
    sys.exit(app.exec())
