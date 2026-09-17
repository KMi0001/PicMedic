"""
gui/city_organize_screen.py 테스트

2026-09-17 실사용 리포트: 도시별 정리 화면이 여전히 느림. 원인은
_build_city_card()가 한 도시의 파일마다 위젯(_ClickableFileRow)을 전부
만들었던 것 — 실측: 사진 8,000장짜리 도시 카드 하나 만드는 데 약 2초.
팬/줌마다(디바운스해도) 화면에 보이는 도시 카드를 전부 다시 그리므로,
사진이 몰린 도시(예: "서울" 수천~수만 장) 하나만 있어도 매번 몇 초씩 멎는
것처럼 보였다. 카드당 행 개수 상한(_MAX_FILE_ROWS_PER_CARD)을 걸어 카드
생성 비용을 파일 수와 무관하게 일정하게 만들었다 — 이 테스트가 그 상한을
고정한다.

2026-09-18 사용자 리포트: "접기(그룹화)를 안 만들어주는거야 ㅠㅠ" — 지도에
도시가 여러 개 보이면 카드마다 파일 목록이 처음부터 다 펼쳐져서 화면이
감당 안 될 만큼 길어졌다. 카드 자체를 기본으로 접고, 헤더를 눌러야
펼쳐지도록 바꿨다 — 이때 행 위젯도 그제서야 처음 만들어진다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from gui.city_organize_screen import CityOrganizeScreen, _ClickableFileRow
from models.file_info import FileInfo, FileStatus, RecoveryPossibility


def _info(i: int) -> FileInfo:
    return FileInfo(
        path=f"C:/fake/IMG_{i}.jpg",
        filename=f"IMG_{i}.jpg",
        extension=".jpg",
        status=FileStatus.NORMAL,
        recoverable=RecoveryPossibility.NOT_RECOVERABLE,
        latitude=37.5665,
        longitude=126.9780,
    )


def _header_and_body(card) -> tuple[QToolButton, QWidget]:
    """_build_city_card()가 만드는 카드는 항상 [헤더 토글버튼, 본문 위젯]
    2개뿐이다(본문 안의 파일 행은 헤더를 펼쳐야 만들어진다)."""
    header_btn = card.findChildren(QToolButton)[0]
    body = card.layout().itemAt(1).widget()
    return header_btn, body


def test_group_centroid_helper():
    """_refresh_map이 도시 그룹의 지도 좌표로 쓰는 값 — 그룹 안 모든 파일의
    GPS 평균."""
    files = [
        FileInfo(
            path="a", filename="a", extension=".jpg", status=FileStatus.NORMAL,
            recoverable=RecoveryPossibility.NOT_RECOVERABLE, latitude=10.0, longitude=20.0,
        ),
        FileInfo(
            path="b", filename="b", extension=".jpg", status=FileStatus.NORMAL,
            recoverable=RecoveryPossibility.NOT_RECOVERABLE, latitude=20.0, longitude=40.0,
        ),
    ]
    centroid = CityOrganizeScreen._group_centroid(files)
    check("중심점이 평균 좌표와 일치", centroid == (15.0, 30.0), centroid)


def test_refresh_map_uses_group_centroid_not_first_file():
    """2026-09-18 사용자 리포트: "지도에서 서울을 선택하면 인천으로
    포커싱되고 있어" — 원인은 그룹의 지도 좌표를 files[0](그룹의 첫 파일)
    하나로만 정했던 것. 사진 촬영/정렬 순서상 우연히 그 첫 파일의 GPS가
    그룹 라벨("서울")과 안 맞는 위치(인천 근처)면 핀 자체가 거기 찍혔고,
    그 핀을 클릭(포커스)하면 그 잘못된 좌표로 확대됐다. 그룹 전체 파일의
    GPS 평균을 쓰도록 고쳤으니, 튀는 첫 파일 하나가 있어도 핀 위치가
    나머지 정상 파일들 쪽에 훨씬 가까워야 한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    screen.map_view.resize(800, 600)
    screen.map_view.show()

    seoul_lat, seoul_lon = 37.5665, 126.9780
    incheon_like_outlier = FileInfo(
        path="C:/fake/outlier.jpg", filename="outlier.jpg", extension=".jpg",
        status=FileStatus.NORMAL, recoverable=RecoveryPossibility.NOT_RECOVERABLE,
        latitude=37.30, longitude=126.50,  # 서울 그룹의 "첫 파일"이지만 인천 쪽으로 치우친 좌표
    )
    # files[0]이 바로 그 튀는 좌표가 되도록 맨 앞에 둔다 — 예전 버그(files[0]만
    # 씀)였다면 핀이 이 좌표에 찍혔을 것.
    seoul_files = [incheon_like_outlier] + [_info(i) for i in range(9)]  # 나머지 9장은 정상 서울 좌표
    screen._groups = [("서울", seoul_files)]
    screen._files = seoul_files
    screen._file_to_label = {f.path: "서울" for f in seoul_files}

    screen._refresh_map()

    map_lat, map_lon, count, label, _cc, _province = screen.map_view._raw_points[0]
    check("지도 점이 서울 그룹 하나만큼 생김", count == 10, count)
    dist_to_seoul = ((map_lat - seoul_lat) ** 2 + (map_lon - seoul_lon) ** 2) ** 0.5
    dist_to_outlier = ((map_lat - incheon_like_outlier.latitude) ** 2 + (map_lon - incheon_like_outlier.longitude) ** 2) ** 0.5
    check(
        "핀 좌표가 튀는 첫 파일보다 정상 서울 좌표 쪽에 훨씬 가까움(평균이라 9:1로 당겨짐)",
        dist_to_seoul < dist_to_outlier,
        (map_lat, map_lon, dist_to_seoul, dist_to_outlier),
    )


def test_city_card_starts_collapsed():
    """카드는 기본적으로 접혀 있어야(헤더만 보임) 하고, 파일 행 위젯은
    펼치기 전까진 아예 만들어지지 않아야 한다 — 상한(_MAX_FILE_ROWS_PER_CARD)을
    둔 이유였던 카드 생성 비용이, 지도에 도시 카드 여러 개가 동시에 떠
    있어도 전혀 들지 않아야 하기 때문(접힌 카드는 헤더 버튼 하나뿐)."""
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    files = [_info(i) for i in range(10)]
    card = screen._build_city_card("서울", files)

    header_btn, body = _header_and_body(card)
    check("카드 레이아웃은 헤더+본문 2개뿐(접힌 상태)", card.layout().count() == 2, card.layout().count())
    check("헤더 버튼이 기본으로 접혀 있음(체크 안 됨)", not header_btn.isChecked())
    check("접힌 상태 문구는 ▸로 시작", header_btn.text().startswith("▸"), header_btn.text())
    check("본문이 기본으로 숨겨져 있음", body.isHidden())
    check("펼치기 전에는 파일 행 위젯이 하나도 안 만들어짐", len(card.findChildren(_ClickableFileRow)) == 0)

    header_btn.setChecked(True)
    check("헤더를 누르면 본문이 보임(isHidden=False)", not body.isHidden())
    check("펼친 상태 문구는 ▾로 시작", header_btn.text().startswith("▾"), header_btn.text())
    check("펼치면 그제서야 파일 행 위젯이 만들어짐", len(card.findChildren(_ClickableFileRow)) == 10)

    header_btn.setChecked(False)
    check("다시 접으면 본문이 숨겨짐", body.isHidden())
    check(
        "접어도 위젯은 재사용됨(다시 만들지 않고 그대로 10개)",
        len(card.findChildren(_ClickableFileRow)) == 10,
    )


def test_selecting_city_card_moves_map():
    """2026-09-18 사용자 요청: "마카오 선택하면 마카오로 지도를 움직였으면
    좋겠는데" — 도시 카드 헤더를 클릭해서 펼치면(선택하면) 지도가 그 도시
    위치로 이동해야 한다. 단, _refresh_region_list가 팬/줌마다 카드를
    통째로 다시 그리며 펼침 상태를 프로그램적으로 복원(setChecked)할 때는
    지도가 또 움직이면 안 된다 — 안 그러면 카드 하나만 펼쳐져 있어도 사용자가
    지도를 팬/줌할 때마다 그 도시로 도로 끌려간다. QToolButton.click()은
    실제 클릭처럼 clicked 신호까지 내지만, setChecked()는 toggled만 내고
    clicked는 안 낸다는 Qt 차이를 이용해 구분한다."""
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    screen.map_view.resize(800, 600)
    screen.map_view.show()
    screen.map_view.resetTransform()
    screen.map_view.fitInView(QRectF(-180, -90, 360, 180), Qt.KeepAspectRatio)

    files = [_info(i) for i in range(3)]  # 서울 좌표(37.5665, 126.9780) 고정
    card = screen._build_city_card("서울", files)
    header_btn, _ = _header_and_body(card)

    header_btn.click()  # 실제 클릭 시뮬레이션
    app.processEvents()
    visible = screen.map_view.mapToScene(screen.map_view.viewport().rect()).boundingRect()
    check(
        "카드를 클릭하면 지도가 그 도시 좌표를 포함하도록 이동함",
        visible.contains(126.9780, -37.5665),
        visible,
    )
    check("클릭 후 화면이 세계 지도 전체만큼 넓지는 않음(실제로 확대됨)", visible.width() < 300, visible.width())

    # _refresh_region_list가 다시 그릴 때처럼, 같은 라벨로 새 카드를 만들면
    # _expanded_city_labels에 남아있는 상태를 setChecked로 복원한다.
    visible_before_restore = visible
    card2 = screen._build_city_card("서울", files)
    header_btn2, body2 = _header_and_body(card2)
    check("같은 라벨의 새 카드는 펼침 상태로 복원됨", header_btn2.isChecked())
    check("복원된 카드도 본문이 보임", not body2.isHidden())
    app.processEvents()
    visible_after_restore = screen.map_view.mapToScene(screen.map_view.viewport().rect()).boundingRect()
    check(
        "프로그램적 복원(setChecked)만으로는 지도가 다시 움직이지 않음",
        visible_after_restore == visible_before_restore,
        visible_after_restore,
    )


def test_city_card_row_count_is_capped():
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    cap = screen._MAX_FILE_ROWS_PER_CARD

    small_files = [_info(i) for i in range(10)]
    small_card = screen._build_city_card("서울", small_files)
    header_btn, body = _header_and_body(small_card)
    header_btn.setChecked(True)  # 펼쳐야 실제로 행이 만들어짐
    check(
        "상한보다 적은 도시는 파일 수만큼 행이 생김(본문 10개)",
        body.layout().count() == 10,
        body.layout().count(),
    )

    huge_files = [_info(i) for i in range(cap + 500)]
    huge_card = screen._build_city_card("서울", huge_files)
    huge_header_btn, huge_body = _header_and_body(huge_card)
    huge_header_btn.setChecked(True)
    # 파일 행(상한만큼) + "...외 N장 더" 안내 1줄.
    check(
        f"상한({cap})을 넘는 도시는 행이 상한만큼만 생김(+ 안내 문구 1줄)",
        huge_body.layout().count() == cap + 1,
        huge_body.layout().count(),
    )

    t0 = time.perf_counter()
    big_card = screen._build_city_card("서울", [_info(i) for i in range(30000)])
    big_header_btn, _ = _header_and_body(big_card)
    big_header_btn.setChecked(True)  # 만들기 + 펼치기까지 포함해서 실측
    elapsed = time.perf_counter() - t0
    check(
        f"3만 장짜리 도시 카드도 만들고 펼치는 데 1초 안 걸림(실측 {elapsed:.3f}초)",
        elapsed < 1.0,
    )


def test_city_card_toggle_expands_and_collapses():
    """2026-09-17 사용자 요청: "목록의 접기펴기는 왜 구현이 안된거야?" — 상한
    넘는 파일은 "더 보기" 버튼을 눌러야만 실제로 행 위젯을 만든다(상한을 둔
    이유인 카드 생성 비용을 그대로 지킴 — 접혀 있는 동안은 안 만듦), 다시
    누르면 접힌다(만든 위젯은 재사용, 숨기기만)."""
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    cap = screen._MAX_FILE_ROWS_PER_CARD
    remaining = 37
    files = [_info(i) for i in range(cap + remaining)]
    card = screen._build_city_card("서울", files)
    header_btn, body = _header_and_body(card)
    header_btn.setChecked(True)  # 카드 자체를 먼저 펼쳐야 안의 "더 보기" 토글이 생김

    toggle_btns = body.findChildren(QToolButton)
    check("더 보기 토글 버튼이 정확히 1개 있음", len(toggle_btns) == 1, len(toggle_btns))
    toggle_btn = toggle_btns[0]
    check("접힌 상태 기본 문구", "더 보기" in toggle_btn.text(), toggle_btn.text())

    count_before_expand = body.layout().count()
    check(
        "펼치기 전에는 상한 넘는 행이 아직 안 만들어짐(상한+토글버튼)",
        count_before_expand == cap + 1,
        count_before_expand,
    )

    toggle_btn.setChecked(True)  # 실제 클릭 대신 상태만 토글(버튼 자체는 QTest로 이미 다른 화면에서 검증된 패턴)
    count_after_expand = body.layout().count()
    check(
        f"펼치면 남은 {remaining}개 행이 실제로 추가됨",
        count_after_expand == count_before_expand + remaining,
        count_after_expand,
    )
    check("펼친 상태 문구가 '접기'로 바뀜", toggle_btn.text() == "▾ 접기", toggle_btn.text())

    all_rows = body.findChildren(_ClickableFileRow)
    check("행 위젯 총 개수가 전체 파일 수와 일치", len(all_rows) == len(files), len(all_rows))
    extra_rows = all_rows[cap:]
    # isVisible()은 card 자체가 화면에 show()되지 않으면 조상 체인 때문에
    # 항상 False라 신뢰할 수 없다 — isHidden()은 이 위젯에 직접 hide()/
    # setVisible(False)가 불렸는지만 보는 값이라 여기서는 이게 맞는 확인 방법.
    check("펼친 뒤 추가 행들이 숨김 해제됨(isHidden=False)", all(not w.isHidden() for w in extra_rows))

    toggle_btn.setChecked(False)
    check(
        "접어도 위젯 개수는 그대로임(다시 만들지 않고 숨기기만)",
        body.layout().count() == count_after_expand,
        body.layout().count(),
    )
    check("접힌 뒤 추가 행들이 다시 숨겨짐(isHidden=True)", all(w.isHidden() for w in extra_rows))
    check("접힌 상태 문구로 되돌아감", "더 보기" in toggle_btn.text(), toggle_btn.text())


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_group_centroid_helper()
    test_refresh_map_uses_group_centroid_not_first_file()
    test_city_card_starts_collapsed()
    test_selecting_city_card_moves_map()
    test_city_card_row_count_is_capped()
    test_city_card_toggle_expands_and_collapses()
    print("OK")
