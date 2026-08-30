"""
gui/result_screen.py 테스트

복구 불가능한(완전 손상) 파일은 체크박스가 비활성화되어 있고, 전체선택/행선택
등 어떤 경로로도 실제 복구 대상 목록에 포함되지 않는지 확인한다.
(PRD_MVP우선순위.md '남은 갭 #5')
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.result_screen import ResultScreen
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


def run():
    passed = failed = 0

    def check(label, cond, extra=""):
        nonlocal passed, failed
        print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")
        if cond:
            passed += 1
        else:
            failed += 1

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

    print(f"\n총 {passed + failed}개 중 {passed}개 통과, {failed}개 실패")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
