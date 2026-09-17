"""
utils/topojson.py

assets/world_countries_50m.json(Natural Earth 1:50m 국가 경계 — 퍼블릭
도메인 데이터를 topojson/world-atlas가 TopoJSON으로 재배포, ISC 유사
라이선스, https://github.com/topojson/world-atlas)를 그리려면 정수로 양자화된 델타 인코딩 좌표(arcs)를 실제 위경도로 복원해야
한다 — JS의 topojson-client가 하는 일을 Python으로 옮긴 최소 디코더(이
프로젝트에 필요한 "land/countries 객체 -> 폴리곤 좌표 리스트" 변환만 지원,
범용 TopoJSON 파서 아님). gui/city_map_view.py(Phase 2 "도시별 정리" 지도)
에서 쓴다. experiments/city_organize_prototype에서 먼저 검증됨.
"""

from __future__ import annotations


def _decode_arc(
    arc: list[list[int]], scale: tuple[float, float], translate: tuple[float, float]
) -> list[tuple[float, float]]:
    """정수 델타 인코딩 arc 하나 -> [(lon, lat), ...]. 첫 점은 절대 좌표,
    이후는 이전 점과의 차이(delta)로 저장돼 있어 누적합이 필요하다."""
    x = y = 0
    points = []
    for dx, dy in arc:
        x += dx
        y += dy
        points.append((x * scale[0] + translate[0], y * scale[1] + translate[1]))
    return points


def _arc_points(arc_index: int, decoded_arcs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """TopoJSON 스펙: 음수 인덱스는 '~index'(비트 NOT)로 인코딩된, 반대 방향으로
    이어붙일 arc를 뜻한다."""
    if arc_index >= 0:
        return decoded_arcs[arc_index]
    return list(reversed(decoded_arcs[~arc_index]))


def _assemble_rings(
    geometry: dict, decoded_arcs: list[list[tuple[float, float]]]
) -> list[list[tuple[float, float]]]:
    """Polygon/MultiPolygon geometry 하나를 [(lon, lat), ...] 링 목록으로
    조립한다(폴리곤의 구멍/외곽 구분 없이 전부 평평한 링 목록으로 — 장식용
    지도라 위상 구분까지는 필요 없음)."""
    polygons = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
    rings: list[list[tuple[float, float]]] = []
    for polygon in polygons:
        for ring_arc_indices in polygon:
            ring: list[tuple[float, float]] = []
            for arc_index in ring_arc_indices:
                pts = _arc_points(arc_index, decoded_arcs)
                if ring and ring[-1] == pts[0]:
                    ring.extend(pts[1:])  # 이어지는 arc의 시작점은 이전 끝점과 중복
                else:
                    ring.extend(pts)
            rings.append(ring)
    return rings


def _load_topology(topojson_path: str) -> tuple[dict, list[list[tuple[float, float]]]]:
    import json

    with open(topojson_path, encoding="utf-8") as f:
        topo = json.load(f)
    scale = tuple(topo["transform"]["scale"])
    translate = tuple(topo["transform"]["translate"])
    decoded_arcs = [_decode_arc(arc, scale, translate) for arc in topo["arcs"]]
    return topo, decoded_arcs


def load_country_polygons(topojson_path: str) -> list[tuple[str, list[list[tuple[float, float]]]]]:
    """countries-*.json의 각 나라를 (영문/현지 이름, 링 목록)으로 반환한다 —
    core/country_names_ko.py로 한국어 라벨을 붙이고, gui/city_map_view.py가
    나라 윤곽(국경선 포함)과 이름 라벨을 그리는 데 쓴다."""
    topo, decoded_arcs = _load_topology(topojson_path)
    countries = topo["objects"]["countries"]
    result: list[tuple[str, list[list[tuple[float, float]]]]] = []
    for geometry in countries["geometries"]:
        name = geometry.get("properties", {}).get("name", "")
        result.append((name, _assemble_rings(geometry, decoded_arcs)))
    return result


def load_province_polygons(topojson_path: str) -> list[tuple[str, str, list[list[tuple[float, float]]]]]:
    """assets/kr_provinces_10m.json(Natural Earth 1:10m Admin-1 States/Provinces
    — naturalearthdata.com 공식 배포, 퍼블릭 도메인)의 대한민국 시/도 17개를
    (영문 이름, 한국어 이름, 링 목록)으로 반환한다. gui/city_map_view.py가
    도 경계선을 그리는 데 쓴다(2026-09-18, 사용자 요청 — "도 단위로는 얇은
    선이라도 나뉘어 있음 좋을거 같아서"). load_country_polygons과 같은
    구조(scale=[1,1]/translate=[0,0]로 델타 인코딩=원본 좌표 차이가 되게
    만들어서 quantization 없이 이 디코더를 그대로 재사용)라 별도 파서가
    필요 없다."""
    topo, decoded_arcs = _load_topology(topojson_path)
    provinces = topo["objects"]["provinces"]
    result: list[tuple[str, str, list[list[tuple[float, float]]]]] = []
    for geometry in provinces["geometries"]:
        props = geometry.get("properties", {})
        name = props.get("name", "")
        name_ko = props.get("name_ko", "")
        result.append((name, name_ko, _assemble_rings(geometry, decoded_arcs)))
    return result
