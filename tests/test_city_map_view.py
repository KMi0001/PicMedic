"""
gui/city_map_view.py 테스트

2026-09-17 사용자 요청 1: 화면에 나라가 2개 이상 보이면 도시 단위 대신
나라 단위로 뭉쳐서 보여준다(여러 나라의 도시 라벨이 한꺼번에 보이면
어지럽다는 피드백).
2026-09-17 사용자 요청 2(같은 날 후속): 한 나라 안에서도 도시가 너무 많이
보이면(실사용 4만 6천 장 규모 — 도시 수십 개) 시/도 단위로 한 단계 더
뭉친다.
실제 QGraphicsView 픽셀 렌더링까지는 확인하지 않고, 모드 전환
(_marker_mode)과 마커 개수/집계가 올바른지만 확인한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QRectF
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from gui.city_map_view import CityMapView, _CityMarker


def test_city_map_aggregates_by_country_when_multiple_visible():
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 한국 2곳 + 일본 2곳 + 베트남 1곳 = 3개국, 5개 도시 그룹.
    points = [
        (37.5665, 126.9780, 8, "서울", "KR", "서울"),
        (35.1796, 129.0756, 3, "부산", "KR", "부산"),
        (35.6762, 139.6503, 5, "도쿄", "JP", "Tokyo"),
        (34.6937, 135.5023, 2, "오사카", "JP", "Osaka"),
        (21.0278, 105.8342, 4, "하노이", "VN", "Hanoi"),
    ]
    view.set_points(points)

    # 세계 전체를 보면 3개국이 다 보이므로 나라 단위로 뭉쳐야 한다.
    view.resetTransform()
    view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)
    view.view_changed.emit()

    check("여러 나라가 보이면 country 모드로 전환됨", view._marker_mode == "country", view._marker_mode)
    check("나라 단위로 뭉치면 마커가 나라 수(3)만큼만 생김", len(view._markers) == 3, len(view._markers))

    total_label_counts = sorted(int(m.label_text().split("(")[1].rstrip(")")) for m in view._markers)
    check(
        "나라별 사진 개수가 정확히 합산됨(한국 11 / 일본 7 / 베트남 4)",
        total_label_counts == [4, 7, 11],
        total_label_counts,
    )

    # 한국만 보이게 바짝 확대하면 도시 단위로 돌아가야 한다(도시 수가
    # 시/도 임계값보다 적으므로 province를 거치지 않고 바로 city).
    view.center_on(36.5, 127.8, span_deg=2.0)

    check("도시가 적은 한 나라만 보이면 city 모드로 돌아감", view._marker_mode == "city", view._marker_mode)
    check("도시 모드에서는 마커가 도시 그룹 수(5)만큼 있음", len(view._markers) == 5, len(view._markers))


def test_city_map_aggregates_by_province_when_too_many_cities():
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 한 나라(KR) 안에 도시 20개(임계값 15 초과) — 절반은 경기도, 절반은 강원도.
    points = []
    for i in range(10):
        points.append((37.0 + i * 0.05, 127.0 + i * 0.02, 2, f"도시경기{i}", "KR", "경기도"))
    for i in range(10):
        points.append((37.5 + i * 0.05, 128.5 + i * 0.02, 3, f"도시강원{i}", "KR", "강원도"))
    view.set_points(points)

    view.resetTransform()
    view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)
    view.view_changed.emit()

    check(
        "도시 20개(임계값 15 초과)가 한 나라 안에 보이면 province 모드로 전환됨",
        view._marker_mode == "province",
        view._marker_mode,
    )
    check("시/도 2개(경기도/강원도)만큼만 마커가 생김", len(view._markers) == 2, len(view._markers))

    labels = sorted(m.label_text() for m in view._markers)
    check(
        "시/도별 사진 개수가 정확히 합산됨(경기도 20장, 강원도 30장)",
        labels == ["강원도 (30)", "경기도 (20)"],
        labels,
    )

    # 도시 15개 이하로 줄어들면(예: 경기도만 남게 확대) city 단위로 돌아가야 한다.
    view.resetTransform()
    view.fitInView(QRectF(126.9, -37.55, 0.6, 0.6), Qt.KeepAspectRatio)
    view.view_changed.emit()

    check("도시 수가 임계값 이하로 줄면 city 모드로 돌아감", view._marker_mode == "city", view._marker_mode)


def test_set_points_fits_view_to_all_countries_initially():
    """2026-09-18 사용자 리포트: "나라별로 있으면 지도에 다보이기로 하지
    않았나?" — 실제로는 위젯이 뜨자마자(스캔 결과가 아직 없을 때) resizeEvent가
    KOREA_CENTER 언저리 14도 박스로 한 번 맞춰버린 뒤로는, 나중에 set_points로
    진짜 데이터(예: 한국+브라질처럼 서로 먼 나라)가 들어와도 다시는 자동으로
    맞춰주지 않아서 그 박스 밖 나라는 화면에 아예 안 잡혔다(나라 단위 집계도
    안 됨 — _visible_points가 애초에 못 봄). set_points가 실제 데이터를 처음
    받으면 그 데이터 전체가 보이게 자동으로 맞춰야 한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()  # resizeEvent가 먼저 발생 — 이 시점엔 아직 데이터가 없어 KOREA_CENTER로 맞춰짐
    app.processEvents()

    # 한국과 지구 반대편 브라질 — KOREA_CENTER의 기본 14도 span으로는 절대
    # 같이 안 보이는 조합.
    points = [
        (37.5665, 126.9780, 8, "서울", "KR", "서울"),
        (-23.5505, -46.6333, 3, "상파울루", "BR", "Sao Paulo"),
    ]
    view.set_points(points)  # 수동으로 fitInView/center_on을 따로 부르지 않음 — 자동으로 맞춰져야 함
    app.processEvents()

    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    check(
        "set_points만으로 서울이 화면 범위 안에 들어옴(수동 확대 없이)",
        visible.contains(126.9780, -37.5665),
        visible,
    )
    check(
        "set_points만으로 상파울루도 화면 범위 안에 들어옴(수동 확대 없이)",
        visible.contains(-46.6333, 23.5505),
        visible,
    )
    check("두 나라가 다 보이니 country 모드로 집계됨", view._marker_mode == "country", view._marker_mode)
    check("나라 단위 마커가 2개 생김", len(view._markers) == 2, len(view._markers))


def test_marker_colors_vary_by_key():
    """2026-09-18 사용자 요청 히스토리: 처음엔 "핀 색상을 좀 다양하게 할 수
    있나?"로 나라코드별 색을 넣었는데(같은 나라 도시는 전부 같은 색),
    바로 이어서 "핀 색상은 도시별로 바꿔줘"로 바뀌었다 — 지금은 마커가
    대표하는 단위 자체(도시 라벨/(나라,시도) 쌍/나라 코드)로 색을 나눈다.
    같은 나라 안 도시들도 서로 다른 색이 나와야 하는 게 이번 요청의
    핵심이고, 같은 값은 (같은 프로세스 안에서) 항상 같은 색이 결정적으로
    나와야 한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 같은 나라(KR) 안에 도시 4개 — 나라가 같아도 도시마다 색이 달라야 한다.
    points = [
        (37.5665, 126.9780, 8, "서울", "KR", "서울"),
        (35.1796, 129.0756, 3, "부산", "KR", "부산"),
        (35.8714, 128.6014, 2, "대구", "KR", "대구"),
        (35.1595, 126.8526, 1, "광주", "KR", "광주"),
    ]
    view.set_points(points)
    view.resetTransform()
    view.fitInView(QRectF(126, -38, 4, 4), Qt.KeepAspectRatio)
    view.view_changed.emit()
    check("도시 4개가 city 모드로 보임(나라 1개·도시 4개 < 임계값)", view._marker_mode == "city", view._marker_mode)
    check("도시 마커가 4개 있음", len(view._markers) == 4, len(view._markers))

    city_colors = {m.label_text().split(" (")[0]: m._color.name() for m in view._markers}
    check(
        "같은 나라 안 도시들도 서로 다른 색을 가짐(도시별 다양화)",
        len(set(city_colors.values())) == 4,
        city_colors,
    )

    seoul_color_first = city_colors["서울"]
    view.set_points(points)  # 팬/줌으로 마커가 다시 만들어지는 상황 흉내
    seoul_marker_again = next(m for m in view._markers if "서울" in m.label_text())
    check(
        "같은 도시는 다시 만들어도 항상 같은 색(결정적)",
        seoul_marker_again._color.name() == seoul_color_first,
        (seoul_marker_again._color.name(), seoul_color_first),
    )


def test_marker_shape_is_circle_not_full_label_bounding_rect():
    """2026-09-18 사용자 리포트: "서울 선택하면 인천으로", "대한민국
    선택해도 대만으로 가고 있다" — 지도 핀 좌표를 그룹 평균으로 고쳐도
    (직전 두 커밋) 재현이 그대로였던 진짜 원인. _CityMarker가 shape()를
    따로 안 줘서 Qt가 기본값으로 boundingRect() 전체(원 오른쪽으로 라벨
    텍스트를 위해 최대 220 화면단위 넓힌 사각형)를 클릭 판정 영역으로
    썼다 — 마커 두 개가 화면에서 가까우면 한쪽의 "안 보이는" 라벨 영역이
    반대쪽의 눈에 보이는 원 위까지 뒤덮어서, 분명 A의 원을 눌렀는데 스택에
    있는 B가 대신 클릭됐다. shape()를 실제 원 크기로 좁혔으니, 라벨
    텍스트가 그려지는 자리(원에서 한참 오른쪽)는 더 이상 클릭 판정에 걸리면
    안 된다."""
    marker = _CityMarker(radius=8, label="테스트도시")
    shape = marker.shape()

    check("원 중심은 클릭 판정 영역 안에 있음", shape.contains(QPointF(0, 0)))
    check("원 가장자리 바로 안쪽도 클릭 판정 영역 안에 있음", shape.contains(QPointF(7, 0)))
    check(
        "라벨 텍스트가 그려지는 자리(원 오른쪽 멀리)는 클릭 판정 영역 밖(예전엔 220 단위까지 걸렸음)",
        not shape.contains(QPointF(100, 4)),
    )
    check(
        "boundingRect()는 여전히 라벨 영역까지 넉넉히 포함함(그리기/무효화 범위 계산용 — shape와는 다른 목적)",
        marker.boundingRect().contains(QPointF(100, 4)),
    )


def test_close_markers_click_hits_correct_pin_not_neighbors_label_area():
    """위 shape() 단위 테스트가 고친 매커니즘을, 실제 사용자 시나리오
    ("세계지도 상태에서 대한민국 선택해도 다른나라로 가고 있어.. (대만으로
    가고있네)")에 가깝게 재현한다. 대만은 대한민국보다 서쪽(왼쪽 화면)에
    있고 라벨은 마커 오른쪽에 그려지므로, 대만 마커의 "라벨 영역"이 동쪽
    (오른쪽)으로 뻗어 대한민국 마커의 원 위까지 뒤덮을 수 있을 만큼
    가깝게(화면상 110px 안팎) 배치한다 — shape()를 고치기 전이었다면
    itemAt()이 대만 마커를 돌려줬을 배치."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    points = [
        (37.5665, 126.9780, 13, "서울", "KR", "서울"),
        (25.0330, 121.5654, 5, "타이베이", "TW", "Taipei"),
    ]
    view.set_points(points)
    view.resetTransform()
    view.fitInView(QRectF(80, -60, 120, 90), Qt.KeepAspectRatio)
    view.view_changed.emit()
    check("나라 2개가 country 모드로 보임", view._marker_mode == "country", view._marker_mode)

    kr_marker = next(m for m in view._markers if "대한민국" in m.label_text())
    tw_marker = next(m for m in view._markers if "대만" in m.label_text())
    gap_px = (view.mapFromScene(kr_marker.pos()) - view.mapFromScene(tw_marker.pos())).manhattanLength()
    check(f"두 마커가 화면상 220px보다 가까움(겹침 재현 전제, 실측 {gap_px}px)", gap_px < 220, gap_px)

    kr_screen_pos = view.mapFromScene(kr_marker.pos())
    hit = view.itemAt(kr_screen_pos)
    check(
        "대한민국 핀의 정확한 화면 위치를 클릭하면 대한민국 마커가 잡힘(이웃 마커의 라벨 영역에 안 뺏김)",
        hit is kr_marker,
        hit.label_text() if isinstance(hit, _CityMarker) else hit,
    )


def test_overlay_buttons_recenter_and_zoom():
    """2026-09-17 사용자 요청(같은 날 후속): "지도 안에 버튼을 만들자. gps를
    추적할 순 없으니까 사진이 가장많은 나라 기준으로 지도를 표기해주는
    버튼이랑 +/- 확대 축소 해주는 버튼." 재중심 버튼은 GPS가 아니라
    self._raw_points 안에서 사진 수를 나라별로 합산해 가장 많은 나라로
    이동해야 한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    check("오버레이 툴바가 생성됨", hasattr(view, "_overlay_toolbar"))
    check(
        "재중심/확대/축소 버튼 3개가 모두 있음",
        hasattr(view, "_recenter_btn") and hasattr(view, "_zoom_in_btn") and hasattr(view, "_zoom_out_btn"),
    )

    # 한국 5장, 일본 20장 -> 일본이 "사진이 가장 많은 나라"여야 한다.
    points = [
        (37.5665, 126.9780, 5, "seoul", "KR", "서울"),
        (35.6762, 139.6503, 20, "tokyo", "JP", "Tokyo"),
    ]
    view.set_points(points)
    check("사진이 가장 많은 나라를 정확히 찾음(일본 20장 > 한국 5장)", view._country_with_most_photos() == "JP")

    before_scale = view.transform().m11()
    view._zoom_by(1.2)
    check("+ 버튼(확대)을 누르면 배율이 커짐", view.transform().m11() > before_scale)

    after_zoom_in = view.transform().m11()
    view._zoom_by(1 / 1.2)
    check("- 버튼(축소)을 누르면 배율이 작아짐", view.transform().m11() < after_zoom_in)

    # 아주 멀리 축소된 상태에서 재중심하면 일본 지점이 화면 안에 들어와야 한다.
    view.resetTransform()
    view.scale(0.001, 0.001)
    view._recenter_to_busiest_country()
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    check(
        "재중심 버튼을 누르면 사진이 가장 많은 나라(일본) 지점이 화면 안에 들어옴",
        visible.contains(139.6503, -35.6762),
        visible,
    )


def test_marker_click_vs_drag():
    """2026-09-17 사용자 리포트: "클릭으로 드래그 하고싶은데 자꾸 확대되서
    길을 잃어" — 핀 위에서 마우스를 누르는 즉시(mousePressEvent) 확대해
    버려서, 그 자리에서 드래그(지도 패닝)를 시작하려던 제스처까지 전부
    확대로 처리되던 버그. 실제 QMouseEvent를 뷰(viewport)에 보내서 진짜
    클릭과 드래그를 구분해서 검증한다(마커 자신의 콜백을 직접 부르는
    test_pin_click_opens_and_closes_view와 달리, 여기는 이벤트 전달 경로
    자체를 검증)."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    points = [
        (37.5665, 126.9780, 5, "seoul", "KR", "서울"),
        (35.6762, 139.6503, 20, "tokyo", "JP", "Tokyo"),
    ]
    view.set_points(points)
    view.resetTransform()
    view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)
    view.view_changed.emit()

    marker = view._markers[0]
    clicked = {"count": 0}
    marker.on_left_click = lambda: clicked.__setitem__("count", clicked["count"] + 1)
    marker_pos = view.mapFromScene(marker.pos())

    check(
        "마커가 마우스 버튼 이벤트를 아예 안 받음(패닝이 핀 위에서도 막히지 않도록)",
        marker.acceptedMouseButtons() == Qt.NoButton,
    )

    # 진짜 클릭(누르고 거의 그 자리에서 뗌) -> on_left_click 호출돼야 함
    app.sendEvent(
        view.viewport(),
        QMouseEvent(QEvent.MouseButtonPress, QPointF(marker_pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    app.sendEvent(
        view.viewport(),
        QMouseEvent(QEvent.MouseButtonRelease, QPointF(marker_pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    app.processEvents()
    check("핀을 클릭(이동 없이 누르고 뗌)하면 on_left_click이 호출됨", clicked["count"] == 1, clicked["count"])

    # 드래그(핀 위에서 눌러서 꽤 이동한 뒤 뗌) -> on_left_click이 호출되면 안 됨
    clicked["count"] = 0
    drag_end = marker_pos + QPoint(60, 40)
    app.sendEvent(
        view.viewport(),
        QMouseEvent(QEvent.MouseButtonPress, QPointF(marker_pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    app.sendEvent(
        view.viewport(), QMouseEvent(QEvent.MouseMove, QPointF(drag_end), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    )
    app.sendEvent(
        view.viewport(),
        QMouseEvent(QEvent.MouseButtonRelease, QPointF(drag_end), Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    app.processEvents()
    check(
        "핀 위에서 눌러서 드래그하면(60,40 이동) on_left_click이 호출되지 않음",
        clicked["count"] == 0,
        clicked["count"],
    )


def test_pin_click_opens_and_closes_view():
    """2026-09-17 사용자 요청(같은 날 후속): "핀별로 열고 닫기 기능 추가".
    좌클릭(핀 열기)은 그 핀이 대표하는 지점들이 화면에 꽉 차게 확대해야
    하고, 우클릭 메뉴의 "축소해서 전체 보기"(핀 닫기)는 전체 데이터가 다시
    보이게 축소해야 한다.

    구현 중 발견한 진짜 버그 회귀 방지: CityMapView의 기본
    transformationAnchor는 AnchorUnderMouse(휠 줌이 마우스 위치를 고정점
    삼게 하려고 켜둠)인데, 이 상태로 fitInView를 그냥 부르면 확대 결과가
    "지금 마우스 커서 위치" 쪽으로 엉뚱하게 쏠린다 — 목표 지점이 아니라
    태평양 한가운데가 보이는 식으로 재현됐었다. _fit_scene_rect가 이걸
    AnchorViewCenter로 임시 전환하는지 확인한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 나라 단위(country) 마커가 확실히 뜨도록 2개국으로 구성 — 핀 클릭 동작
    # 자체는 country/province 어느 단계든 똑같으므로, 조합이 더 간단한
    # 나라 단위로 검증한다.
    points = [
        (37.0, 127.0, 2, "a", "KR", "경기도"),
        (37.45, 127.18, 2, "b", "KR", "경기도"),
        (35.68, 139.77, 3, "c", "JP", "Tokyo"),
    ]
    view.set_points(points)
    view.resetTransform()
    view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)
    view.view_changed.emit()
    check("나라 2개라 country 모드로 시작함(핀 클릭 검증 전제)", view._marker_mode == "country", view._marker_mode)

    kr_marker = next(m for m in view._markers if "대한민국" in m.label_text())
    check("대한민국 핀에 좌클릭 콜백이 연결됨", kr_marker.on_left_click is not None)
    check("대한민국 핀에 우클릭 콜백이 연결됨", kr_marker.on_right_click is not None)

    kr_marker.on_left_click()
    app.processEvents()
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    # 한국 두 지점(37.0~37.45, 127.0~127.18)이 화면 안에 들어와야 하고,
    # 일본 지점(35.68, 139.77)처럼 화면 전체 씬(세계 지도) 크기만큼 넓게
    # 잡혀서는 안 된다 — 마우스 위치로 쏠리는 버그였다면 대개 훨씬 좁거나
    # (0,0) 근처 등 엉뚱한 곳을 보여준다.
    check(
        "핀 클릭(열기) 후 그 핀의 지점들이 화면 범위 안에 들어옴",
        visible.contains(127.0, -37.0) and visible.contains(127.18, -37.45),
        visible,
    )
    check(
        "핀 클릭 후 화면이 세계 지도 전체만큼 넓지는 않음(실제로 확대됐음)",
        visible.width() < 300,
        visible.width(),
    )

    view.zoom_out_to_all()
    app.processEvents()
    visible_after = view.mapToScene(view.viewport().rect()).boundingRect()
    check(
        "축소해서 전체 보기(닫기) 후 모든 지점이 다시 화면 안에 들어옴",
        all(visible_after.contains(lon, -lat) for lat, lon, *_ in points),
        visible_after,
    )


def test_pin_click_respects_max_zoom_cap():
    """2026-09-18 사용자 요청: "확대는 제한을 좀 하자 시/도 이상은 더 확대
    못하게 해줘". 휠/버튼 줌(_zoom_by)은 원래부터 _MAX_SCALE을 넘는 배율
    자체를 거부해서 안전했지만, 핀 클릭이 쓰는 _fit_scene_rect는 rect 크기에
    맞춰 fitInView가 배율을 자동 계산할 뿐 캡을 전혀 안 봤다 — 그래서 점
    하나짜리(폭/높이가 0이라 min_span=0.05 바닥이 적용되는) 핀을 열면
    _MAX_SCALE을 훌쩍 넘겨 확대됐다. _fit_scene_rect가 fitInView 직후 실제
    배율을 캡 안으로 눌러주는지 확인한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 단일 지점(서울 하나) — min_span 바닥이 적용되는, 캡 없이는 가장 깊이
    # 확대되는 케이스.
    points = [(37.5665, 126.9780, 100, "서울", "KR", "서울")]
    view.set_points(points)
    view.resetTransform()
    view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)
    view.view_changed.emit()

    view._fit_scene_rect(view._points_bounds(points))
    app.processEvents()
    actual_scale = view.transform().m11()
    check(
        f"단일 지점 핀을 열어도 _MAX_SCALE({view._MAX_SCALE})을 넘지 않음(실측 {actual_scale:.1f})",
        actual_scale <= view._MAX_SCALE + 1e-6,
        actual_scale,
    )

    # 세계 전체보다도 훨씬 넓은 rect를 억지로 넣어 _MIN_SCALE 쪽 캡도 확인.
    view._fit_scene_rect(QRectF(-3600, -1800, 7200, 3600))
    app.processEvents()
    actual_scale_min = view.transform().m11()
    check(
        f"과도하게 넓은 범위를 열어도 _MIN_SCALE({view._MIN_SCALE}) 밑으로 안 내려감(실측 {actual_scale_min:.4f})",
        actual_scale_min >= view._MIN_SCALE - 1e-6,
        actual_scale_min,
    )


def test_city_map_handles_empty_points():
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(400, 300)
    view.show()

    view.set_points([])
    check("빈 목록이면 마커가 없음", view._markers == [])

    # 빈 목록 이후 다시 채워도 정상 동작해야 한다(초기화 순서 회귀 방지).
    view.set_points([(37.5665, 126.9780, 1, "서울", "KR", "서울")])
    check("빈 목록 다음에 다시 채우면 마커가 생김", len(view._markers) == 1, len(view._markers))


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_city_map_aggregates_by_country_when_multiple_visible()
    test_city_map_aggregates_by_province_when_too_many_cities()
    test_set_points_fits_view_to_all_countries_initially()
    test_marker_colors_vary_by_key()
    test_marker_shape_is_circle_not_full_label_bounding_rect()
    test_close_markers_click_hits_correct_pin_not_neighbors_label_area()
    test_overlay_buttons_recenter_and_zoom()
    test_marker_click_vs_drag()
    test_pin_click_opens_and_closes_view()
    test_pin_click_respects_max_zoom_cap()
    test_city_map_handles_empty_points()
    print("OK")
