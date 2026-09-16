"""
gui/city_map_view.py 테스트

2026-09-17 사용자 요청: 화면에 나라가 2개 이상 보이면 도시 단위 대신
나라 단위로 뭉쳐서 보여준다(여러 나라의 도시 라벨이 한꺼번에 보이면
어지럽다는 피드백). 실제 QGraphicsView 픽셀 렌더링까지는 확인하지 않고,
모드 전환(_marker_mode)과 마커 개수/집계가 올바른지만 확인한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QApplication

from gui.city_map_view import CityMapView


def test_city_map_aggregates_by_country_when_multiple_visible():
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(800, 600)
    view.show()

    # 한국 2곳 + 일본 2곳 + 베트남 1곳 = 3개국, 5개 도시 그룹.
    points = [
        (37.5665, 126.9780, 8, "서울", "KR"),
        (35.1796, 129.0756, 3, "부산", "KR"),
        (35.6762, 139.6503, 5, "도쿄", "JP"),
        (34.6937, 135.5023, 2, "오사카", "JP"),
        (21.0278, 105.8342, 4, "하노이", "VN"),
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

    # 한국만 보이게 바짝 확대하면 도시 단위로 돌아가야 한다.
    view.center_on(36.5, 127.8, span_deg=2.0)

    check("한 나라만 보이면 city 모드로 돌아감", view._marker_mode == "city", view._marker_mode)
    check("도시 모드에서는 마커가 도시 그룹 수(5)만큼 있음", len(view._markers) == 5, len(view._markers))


def test_city_map_handles_empty_points():
    app = QApplication.instance() or QApplication(sys.argv)

    view = CityMapView()
    view.resize(400, 300)
    view.show()

    view.set_points([])
    check("빈 목록이면 마커가 없음", view._markers == [])

    # 빈 목록 이후 다시 채워도 정상 동작해야 한다(초기화 순서 회귀 방지).
    view.set_points([(37.5665, 126.9780, 1, "서울", "KR")])
    check("빈 목록 다음에 다시 채우면 마커가 생김", len(view._markers) == 1, len(view._markers))


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_city_map_aggregates_by_country_when_multiple_visible()
    test_city_map_handles_empty_points()
    print("OK")
