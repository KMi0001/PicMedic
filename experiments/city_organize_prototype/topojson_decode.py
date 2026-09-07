"""
experiments/city_organize_prototype/topojson_decode.py

world-atlas(land-110m.json, Natural Earth 1:110m 육지 경계 — 퍼블릭 도메인
데이터를 topojson/world-atlas가 재배포, ISC 유사 라이선스)는 TopoJSON
형식이라 그대로 그릴 수 없다 — 정수로 양자화된(quantized) 델타 인코딩
좌표(arcs)를 실제 위경도로 복원하는 최소 디코더만 직접 구현한다(JS의
topojson-client가 하는 일을 Python으로 옮긴 것, 이 프로토타입에 필요한
"land 객체 하나 -> 폴리곤 좌표 리스트" 변환만 지원 — 범용 TopoJSON 파서 아님).
"""

from __future__ import annotations


def _decode_arc(arc: list[list[int]], scale: tuple[float, float], translate: tuple[float, float]) -> list[tuple[float, float]]:
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


def load_land_polygons(topojson_path: str) -> list[list[tuple[float, float]]]:
    """land-110m.json의 'land' MultiPolygon을 [(lon, lat), ...] 링 목록으로
    반환한다(폴리곤의 구멍/외곽 구분 없이 전부 채워 그릴 것이므로 평평한
    링 목록이면 충분 — 장식용 배경 지도라 정밀한 위상 구분은 필요 없음)."""
    import json

    with open(topojson_path, encoding="utf-8") as f:
        topo = json.load(f)

    scale = tuple(topo["transform"]["scale"])
    translate = tuple(topo["transform"]["translate"])
    decoded_arcs = [_decode_arc(arc, scale, translate) for arc in topo["arcs"]]

    land = topo["objects"]["land"]
    rings: list[list[tuple[float, float]]] = []
    for geometry in land["geometries"]:
        # MultiPolygon: arcs = [ [ [ring_arc_indices...], ... ], ... ] (폴리곤 목록 -> 링 목록 -> arc 인덱스 목록)
        polygons = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
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


if __name__ == "__main__":
    import sys

    rings = load_land_polygons(sys.argv[1] if len(sys.argv) > 1 else "land110.json")
    print(f"{len(rings)}개 링, 좌표 총 {sum(len(r) for r in rings)}개")
    print("첫 링 앞 5개 좌표:", rings[0][:5])
