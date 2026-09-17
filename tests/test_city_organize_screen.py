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
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtWidgets import QApplication, QToolButton

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


def test_city_card_row_count_is_capped():
    app = QApplication.instance() or QApplication(sys.argv)

    screen = CityOrganizeScreen()
    cap = screen._MAX_FILE_ROWS_PER_CARD

    small_files = [_info(i) for i in range(10)]
    small_card = screen._build_city_card("서울", small_files)
    check(
        "상한보다 적은 도시는 파일 수만큼 행이 생김(10개 + 헤더)",
        small_card.layout().count() == 1 + 10,
        small_card.layout().count(),
    )

    huge_files = [_info(i) for i in range(cap + 500)]
    huge_card = screen._build_city_card("서울", huge_files)
    # 헤더 1 + 파일 행(상한만큼) + "...외 N장 더" 안내 1줄.
    check(
        f"상한({cap})을 넘는 도시는 행이 상한만큼만 생김(+ 안내 문구 1줄)",
        huge_card.layout().count() == 1 + cap + 1,
        huge_card.layout().count(),
    )

    t0 = time.perf_counter()
    screen._build_city_card("서울", [_info(i) for i in range(30000)])
    elapsed = time.perf_counter() - t0
    check(
        f"3만 장짜리 도시 카드도 1초 안에 만들어짐(실측 {elapsed:.3f}초)",
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

    toggle_btn = card.findChildren(QToolButton)
    check("더 보기 토글 버튼이 정확히 1개 있음", len(toggle_btn) == 1, len(toggle_btn))
    toggle_btn = toggle_btn[0]
    check("접힌 상태 기본 문구", "더 보기" in toggle_btn.text(), toggle_btn.text())

    count_before_expand = card.layout().count()
    check(
        "펼치기 전에는 상한 넘는 행이 아직 안 만들어짐(헤더+상한+토글버튼)",
        count_before_expand == 1 + cap + 1,
        count_before_expand,
    )

    toggle_btn.setChecked(True)  # 실제 클릭 대신 상태만 토글(버튼 자체는 QTest로 이미 다른 화면에서 검증된 패턴)
    count_after_expand = card.layout().count()
    check(
        f"펼치면 남은 {remaining}개 행이 실제로 추가됨",
        count_after_expand == count_before_expand + remaining,
        count_after_expand,
    )
    check("펼친 상태 문구가 '접기'로 바뀜", toggle_btn.text() == "▾ 접기", toggle_btn.text())

    all_rows = card.findChildren(_ClickableFileRow)
    check("행 위젯 총 개수가 전체 파일 수와 일치", len(all_rows) == len(files), len(all_rows))
    extra_rows = all_rows[cap:]
    # isVisible()은 card 자체가 화면에 show()되지 않으면 조상 체인 때문에
    # 항상 False라 신뢰할 수 없다 — isHidden()은 이 위젯에 직접 hide()/
    # setVisible(False)가 불렸는지만 보는 값이라 여기서는 이게 맞는 확인 방법.
    check("펼친 뒤 추가 행들이 숨김 해제됨(isHidden=False)", all(not w.isHidden() for w in extra_rows))

    toggle_btn.setChecked(False)
    check(
        "접어도 위젯 개수는 그대로임(다시 만들지 않고 숨기기만)",
        card.layout().count() == count_after_expand,
        card.layout().count(),
    )
    check("접힌 뒤 추가 행들이 다시 숨겨짐(isHidden=True)", all(w.isHidden() for w in extra_rows))
    check("접힌 상태 문구로 되돌아감", "더 보기" in toggle_btn.text(), toggle_btn.text())


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_city_card_row_count_is_capped()
    test_city_card_toggle_expands_and_collapses()
    print("OK")
