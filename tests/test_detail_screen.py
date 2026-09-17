"""
gui/detail_screen.py 테스트

2026-09-18 사용자 요청: "사진 미리보기에 다음/이전 사진이 있을경우
[이전][다음] 노출... 윈도우 기본 사진앱처럼". 방향키(←/→) 로직 자체는
이미 있었지만(2026-09-08), 화면엔 버튼이 없었고 양 끝에서 순환(첫<->끝)
했다. 버튼을 추가하며 순환도 없앴다(끝에 도달하면 그 방향 버튼이
사라지는 것과 동작을 맞추기 위해) — 이 테스트가 새 경계 동작과 버튼
연결을 고정한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtWidgets import QApplication

from gui.detail_screen import DetailScreen
from models.file_info import FileInfo, FileStatus, RecoveryPossibility


def _info(name: str) -> FileInfo:
    return FileInfo(
        path=f"C:/fake/{name}",
        filename=name,
        extension=".jpg",
        status=FileStatus.NORMAL,
        recoverable=RecoveryPossibility.NOT_RECOVERABLE,
    )


def test_nav_buttons_reflect_position_in_group():
    app = QApplication.instance() or QApplication(sys.argv)

    files = [_info(f"{i}.jpg") for i in range(3)]
    screen = DetailScreen()

    screen.set_file(files[0], group=files)
    check("첫 사진에서는 이전 콜백이 없음(이전 버튼 숨김)", screen.preview_viewer._on_prev is None)
    check("첫 사진에서도 다음 콜백은 있음(다음 버튼 보임)", screen.preview_viewer._on_next is not None)

    screen.set_file(files[1], group=files)
    check("가운데 사진에서는 이전 콜백이 있음", screen.preview_viewer._on_prev is not None)
    check("가운데 사진에서는 다음 콜백도 있음", screen.preview_viewer._on_next is not None)

    screen.set_file(files[2], group=files)
    check("마지막 사진에서는 다음 콜백이 없음(다음 버튼 숨김)", screen.preview_viewer._on_next is None)
    check("마지막 사진에서도 이전 콜백은 있음", screen.preview_viewer._on_prev is not None)


def test_nav_buttons_do_not_wrap_around():
    """예전엔 방향키가 양 끝에서 순환(마지막 다음 -> 처음)했는데, 이전/다음
    버튼이 끝에서 숨겨지는 것과 어긋나서 순환을 없앴다(2026-09-18)."""
    app = QApplication.instance() or QApplication(sys.argv)

    files = [_info(f"{i}.jpg") for i in range(3)]
    screen = DetailScreen()
    screen.set_file(files[2], group=files)  # 마지막 사진에서 시작

    check("마지막 사진에서 '다음'을 눌러도 안 넘어감", not screen._step(1))
    check("파일이 그대로 마지막 사진임", screen.current_info is files[2])

    screen.set_file(files[0], group=files)  # 첫 사진에서 시작
    check("첫 사진에서 '이전'을 눌러도 안 넘어감", not screen._step(-1))
    check("파일이 그대로 첫 사진임", screen.current_info is files[0])


def test_nav_button_click_advances_photo():
    """오버레이 다음 버튼을 실제로 클릭하면 진짜로 다음 사진으로 넘어가는지
    끝까지 확인(콜백 존재 여부만이 아니라 실제 동작)."""
    app = QApplication.instance() or QApplication(sys.argv)

    files = [_info(f"{i}.jpg") for i in range(3)]
    screen = DetailScreen()
    screen.set_file(files[0], group=files)

    screen.preview_viewer._next_btn.click()
    check("다음 버튼 클릭으로 둘째 사진으로 이동", screen.current_info is files[1], screen.current_info.filename)

    screen.preview_viewer._prev_btn.click()
    check("이전 버튼 클릭으로 다시 첫 사진으로 이동", screen.current_info is files[0], screen.current_info.filename)


def test_single_file_has_no_nav_buttons():
    app = QApplication.instance() or QApplication(sys.argv)

    screen = DetailScreen()
    screen.set_file(_info("solo.jpg"))  # group 없이
    check("그룹이 없으면 이전 콜백도 없음", screen.preview_viewer._on_prev is None)
    check("그룹이 없으면 다음 콜백도 없음", screen.preview_viewer._on_next is None)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_nav_buttons_reflect_position_in_group()
    test_nav_buttons_do_not_wrap_around()
    test_nav_button_click_advances_photo()
    test_single_file_has_no_nav_buttons()
    print("OK")
