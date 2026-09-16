"""
gui/result_screen.py 테스트

복구 불가능한(완전 손상) 파일은 체크박스가 비활성화되어 있고, 전체선택/행선택
등 어떤 경로로도 실제 복구 대상 목록에 포함되지 않는지 확인한다.
(PRD_MVP우선순위.md '남은 갭 #5')
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check, skip

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gui.result_screen import ResultScreen, _CATEGORY_COLUMN
from models.file_info import FileInfo, FileStatus, RecoveryPossibility
from models.scan_result import ScanResult


def _make_info(name: str, status: FileStatus, recoverable: RecoveryPossibility) -> FileInfo:
    return FileInfo(
        path=f"C:/fake/{name}",
        filename=name,
        extension=".jpg",
        status=status,
        recoverable=recoverable,
    )


def test_result_screen():
    app = QApplication.instance() or QApplication(sys.argv)

    recoverable_file = _make_info("mismatch.jpg", FileStatus.MISMATCH, RecoveryPossibility.RECOVERABLE)
    broken_file = _make_info("broken.jpg", FileStatus.CORRUPTED, RecoveryPossibility.NOT_RECOVERABLE)

    result = ScanResult()
    result.add(recoverable_file)
    result.add(broken_file)

    screen = ResultScreen()
    screen.set_result(result)

    def row_of(info):
        for row in range(screen.table.rowCount()):
            if screen.table.item(row, 0).data(Qt.UserRole) is info:
                return row
        raise AssertionError(f"{info.filename} 행을 못 찾음")

    broken_row = row_of(broken_file)
    ok_row = row_of(recoverable_file)

    broken_check_item = screen.table.item(broken_row, 0)
    ok_check_item = screen.table.item(ok_row, 0)

    check(
        "복구 불가능 파일: 체크박스가 비활성화됨(ItemIsEnabled 없음)",
        not (broken_check_item.flags() & Qt.ItemIsEnabled),
    )
    check(
        "복구 가능 파일: 체크박스는 활성화됨",
        bool(ok_check_item.flags() & Qt.ItemIsEnabled),
    )

    # 헤더 "전체 선택"을 눌러도 복구 불가능한 파일은 선택 목록에 들어가지 않아야 한다
    screen._set_all_checked(Qt.Checked)
    selected = screen._selected_files()
    check("전체선택 후에도 복구 불가능 파일은 제외됨", broken_file not in selected)
    check("전체선택 시 복구 가능 파일은 포함됨", recoverable_file in selected)

    # 행을 직접 선택(하이라이트)해도 체크 상태로 동기화되면 안 된다
    screen._set_all_checked(Qt.Unchecked)
    screen.table.selectRow(broken_row)
    selected2 = screen._selected_files()
    check("행 선택으로도 복구 불가능 파일이 체크되지 않음", broken_file not in selected2)

    # 대량 스캔 결과(수만 장)에서 "전체 선택/해제"가 응답 없음 없이 빠르게 끝나는지 확인.
    # 실사용 재현: 16,965장 스캔 후 전체선택/해제 시 각각 7~10초씩 걸려 "응답 없음"이
    # 뜨던 문제 — 정렬이 켜진 채로 수만 번 setCheckState/selectAll/clearSelection을
    # 부르면 Qt가 매번 재정렬을 검토해 기하급수적으로 느려지는 게 원인이었음.
    # (전체 회귀 테스트를 5,000행 규모로, 넉넉한 시간 제한으로 확인 — 느린 CI 머신도 고려)
    big_files = [
        _make_info(f"img_{i}.jpg", FileStatus.NORMAL, RecoveryPossibility.NOT_APPLICABLE)
        for i in range(5000)
    ]
    big_result = ScanResult()
    for f in big_files:
        big_result.add(f)

    big_screen = ResultScreen()
    big_screen.set_result(big_result)

    t0 = time.perf_counter()
    big_screen._set_all_checked(Qt.Checked)
    select_elapsed = time.perf_counter() - t0
    check(
        f"5,000행 전체선택이 3초 안에 끝남 (실측 {select_elapsed:.2f}초)",
        select_elapsed < 3.0,
    )
    check("5,000행 전체선택 결과 전부 선택됨", len(big_screen._selected_files()) == 5000)

    t0 = time.perf_counter()
    big_screen._set_all_checked(Qt.Unchecked)
    deselect_elapsed = time.perf_counter() - t0
    check(
        f"5,000행 전체해제가 3초 안에 끝남 (실측 {deselect_elapsed:.2f}초)",
        deselect_elapsed < 3.0,
    )
    check("5,000행 전체해제 결과 전부 해제됨", len(big_screen._selected_files()) == 0)

    # 실사용 재현 — "복구 가능한 파일만"(소수)으로 필터해 전체 선택한 뒤 다시
    # "전체"(대량)로 필터를 돌리면 몇 분씩 응답 없음이 뜨던 문제(실측 총
    # 15,591장 중 20장 필터 -> 전체선택 -> "전체"로 복귀 시 약 1,100초).
    # 원인: _populate_table()이 self.table.blockSignals(True)만 걸었는데, 이건
    # QTableWidget 자신의 신호만 막을 뿐 테이블이 내부에 따로 갖는
    # QItemSelectionModel의 selectionChanged는 별개 객체라 안 막힌다 — 선택된
    # 상태에서 행을 다시 채우면 selectionChanged가 행이 늘어나는 동안 여러 번
    # 발생하고, 그때마다 _on_selection_changed가 "전체 행을 훑는" O(행 수)
    # 루프를 또 돌아서 전체적으로 O(행 수^2)가 됐다. _populate_table()에
    # _syncing 재진입 가드를 추가해서 고쳤다.
    N_TOTAL = 8000
    N_MISMATCH = 20
    mixed_files = [
        _make_info(f"mismatch_{i}.jpg", FileStatus.MISMATCH, RecoveryPossibility.RECOVERABLE)
        for i in range(N_MISMATCH)
    ] + [
        _make_info(f"normal_{i}.jpg", FileStatus.NORMAL, RecoveryPossibility.NOT_APPLICABLE)
        for i in range(N_TOTAL - N_MISMATCH)
    ]
    mixed_result = ScanResult()
    for f in mixed_files:
        mixed_result.add(f)

    mixed_screen = ResultScreen()
    mixed_screen.set_result(mixed_result)
    mixed_screen._show_recoverable_only()
    check(f"필터 후 {N_MISMATCH}행만 보임", mixed_screen.table.rowCount() == N_MISMATCH)

    mixed_screen._set_all_checked(Qt.Checked)
    check("필터된 소수 전체선택 정상 동작", len(mixed_screen._selected_files()) == N_MISMATCH)

    t0 = time.perf_counter()
    mixed_screen._filter_by_chip("전체")
    filter_back_elapsed = time.perf_counter() - t0
    check(
        f"소수 선택 후 '전체'({N_TOTAL}행)로 필터 복귀가 3초 안에 끝남 (실측 {filter_back_elapsed:.2f}초)",
        filter_back_elapsed < 3.0,
    )
    check(f"필터 복귀 후 {N_TOTAL}행 전부 보임", mixed_screen.table.rowCount() == N_TOTAL)


def test_category_scan_locks_column_sort():
    """2026-09-17 실사용 리포트: "정리활성 상태인데 카테고리 선택해서 정렬하면
    난장판됨" — 카테고리 분류가 백그라운드에서 도는 동안 그 컬럼으로 정렬을
    걸면, 분류 결과가 하나씩 도착할 때마다(setItem) Qt가 활성 정렬 컬럼
    기준으로 계속 자동 재정렬하면서 행이 튀고 배지(셀 위젯)는 안 따라와
    어긋난다. 분류가 끝날 때까지 그 컬럼 헤더 클릭 자체를 막는 것으로 해결—
    이 테스트는 잠금 상태 전환과 "잠겨있으면 클릭이 씹히는지"를 확인한다."""
    from core.category_finder import is_available

    if not is_available():
        skip("카테고리 분류 자산(assets/photo_category)이 없어 건너뜀")
        return

    app = QApplication.instance() or QApplication(sys.argv)

    result = ScanResult()
    for i in range(5):
        result.add(
            FileInfo(
                path=f"C:/fake/f{i}.jpg",
                filename=f"f{i}.jpg",
                extension=".jpg",
                status=FileStatus.NORMAL,
                recoverable=RecoveryPossibility.NOT_APPLICABLE,
                readable=True,  # readable_files 필터를 통과해야 실제로 워커가 돌고 잠금도 걸림
            )
        )

    screen = ResultScreen()
    screen.show()
    screen.set_result(result)
    header = screen._header

    check("검사 직후 카테고리 워커가 시작됨", screen._hub_worker is not None)
    check(
        f"분류 진행 중엔 카테고리 컬럼이 정렬 잠금됨",
        header._sort_locked_column == _CATEGORY_COLUMN,
        f"실제={header._sort_locked_column}",
    )

    clicked = {"count": 0}
    header.sectionClicked.connect(lambda i: clicked.__setitem__("count", clicked["count"] + 1))
    section_pos = header.sectionViewportPosition(_CATEGORY_COLUMN) + 5
    click_point = QPoint(section_pos, header.height() // 2)

    QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, click_point)
    app.processEvents()
    check("잠긴 동안 카테고리 헤더 클릭이 무시됨(sectionClicked 안 뜸)", clicked["count"] == 0)

    if screen._hub_worker is not None:
        screen._hub_worker.wait(5000)
    for _ in range(100):
        app.processEvents()
        if header._sort_locked_column is None:
            break
    check("분류 완료 후 잠금이 풀림", header._sort_locked_column is None)

    QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, click_point)
    app.processEvents()
    check("잠금 해제 후엔 카테고리 헤더 클릭이 정상 동작함", clicked["count"] == 1)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_result_screen()
    test_category_scan_locks_column_sort()
    print("OK")
