"""
gui/image_viewer.py 테스트

2026-09-18 사용자 요청: "사진 미리보기에 다음/이전 사진이 있을경우
[이전][다음] 노출... 윈도우 기본 사진앱처럼" — ImageViewer에 이전/다음
오버레이 버튼을 추가했다. 콜백이 없는 방향은 버튼이 아예 숨겨져야
한다(윈도우 사진 앱처럼 첫/마지막 사진에서 그쪽 버튼이 안 보임).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PIL import Image
from PySide6.QtWidgets import QApplication

from gui.image_viewer import ImageViewer


def test_nav_buttons_hidden_by_default_and_without_image():
    app = QApplication.instance() or QApplication(sys.argv)

    viewer = ImageViewer()
    check("사진 없을 때 이전 버튼 숨김", viewer._prev_btn.isHidden())
    check("사진 없을 때 다음 버튼 숨김", viewer._next_btn.isHidden())


def test_nav_buttons_visibility_follows_callbacks():
    """콜백을 준 쪽만 보이고, None을 준 쪽은 숨는다 — "이전 사진이 없어서
    다음 사진버튼만 보이는" 예시(사용자 첨부 스크린샷)와 같은 상황."""
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "a.jpg"
        Image.new("RGB", (20, 20), color="red").save(img_path)

        viewer = ImageViewer()
        viewer.set_image_path(str(img_path))
        check("사진 있어도 콜백 등록 전엔 두 버튼 다 숨김", viewer._prev_btn.isHidden() and viewer._next_btn.isHidden())

        prev_calls = {"n": 0}
        next_calls = {"n": 0}
        viewer.set_navigation(lambda: prev_calls.__setitem__("n", prev_calls["n"] + 1), None)
        check("이전 콜백만 주면 이전 버튼만 보임", not viewer._prev_btn.isHidden())
        check("다음 콜백이 없으면 다음 버튼은 숨김", viewer._next_btn.isHidden())

        viewer._prev_btn.click()
        check("이전 버튼 클릭 시 콜백이 호출됨", prev_calls["n"] == 1, prev_calls["n"])

        viewer.set_navigation(None, lambda: next_calls.__setitem__("n", next_calls["n"] + 1))
        check("반대로 다음 콜백만 주면 다음 버튼만 보임", not viewer._next_btn.isHidden())
        check("이전 콜백이 없으면 이전 버튼은 숨김", viewer._prev_btn.isHidden())

        viewer._next_btn.click()
        check("다음 버튼 클릭 시 콜백이 호출됨", next_calls["n"] == 1, next_calls["n"])


def test_nav_buttons_hidden_when_image_cleared():
    """사진이 사라지면(예: 목록에서 선택 해제) 콜백이 남아있어도 버튼은
    안 보여야 한다 — 빈 화면에 이전/다음 버튼만 둥둥 떠 있으면 안 됨."""
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "a.jpg"
        Image.new("RGB", (20, 20), color="red").save(img_path)

        viewer = ImageViewer()
        viewer.set_image_path(str(img_path))
        viewer.set_navigation(lambda: None, lambda: None)
        check("사진 있고 콜백 있으면 둘 다 보임", not viewer._prev_btn.isHidden() and not viewer._next_btn.isHidden())

        viewer.set_pixmap(None)
        check("사진이 없어지면 콜백이 남아있어도 숨김", viewer._prev_btn.isHidden() and viewer._next_btn.isHidden())


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_nav_buttons_hidden_by_default_and_without_image()
    test_nav_buttons_visibility_follows_callbacks()
    test_nav_buttons_hidden_when_image_cleared()
    print("OK")
