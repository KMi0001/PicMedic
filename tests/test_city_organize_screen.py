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

from PySide6.QtWidgets import QApplication

from gui.city_organize_screen import CityOrganizeScreen
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


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_city_card_row_count_is_capped()
    print("OK")
