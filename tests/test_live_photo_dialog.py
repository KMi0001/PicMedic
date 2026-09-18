"""
gui/live_photo_dialog.py 테스트

2026-09-18 사용자 요청: "우클릭 미리보기에서도 이전/다음버튼 추가해주고" —
gui/detail_screen.py에 이전/다음 버튼을 추가한 뒤, 이 화면의 "미리보기"
우클릭 메뉴는 별도 QDialog + 단일 ImageViewer라 그 변경의 영향을 안 받고
여전히 사진 한 장만 보여줬다(다음 짝으로 넘기려면 다이얼로그를 닫고 다시
우클릭해야 했음). 목록 전체 + 클릭한 위치를 같이 넘겨서 이전/다음
오버레이 버튼(gui/image_viewer.py)으로 다른 짝도 훑어볼 수 있게 했다.

_build_live_photo_preview_dialog는 _open_live_photo_preview에서
dialog.exec()(블로킹이라 테스트에서 못 씀)만 뺀 버전이다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PIL import Image
from PySide6.QtWidgets import QApplication

from core.live_photo_finder import LivePhotoMatch
from gui.live_photo_dialog import _build_live_photo_preview_dialog


def test_preview_nav_buttons_reflect_position_and_navigate():
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        matches = []
        for i in range(3):
            img = tmp / f"IMG_{i}.jpg"
            mov = tmp / f"IMG_{i}.MOV"
            Image.new("RGB", (20, 20), color="purple").save(img)
            mov.write_bytes(b"fake")
            matches.append(LivePhotoMatch(image_path=img, mov_path=mov))

        dialog, viewer = _build_live_photo_preview_dialog(None, matches, 0)
        check("첫 짝을 열면 이전 콜백이 없음(이전 버튼 숨김)", viewer._on_prev is None)
        check("첫 짝을 열어도 다음 콜백은 있음(다음 버튼 보임)", viewer._on_next is not None)
        check("제목이 첫 짝의 사진 파일명으로 설정됨", dialog.windowTitle() == "IMG_0.jpg", dialog.windowTitle())

        viewer._next_btn.click()
        check("다음 버튼 클릭으로 둘째 짝으로 넘어감", dialog.windowTitle() == "IMG_1.jpg", dialog.windowTitle())
        check("가운데 짝에서는 이전 콜백도 있음", viewer._on_prev is not None)
        check("가운데 짝에서는 다음 콜백도 있음", viewer._on_next is not None)

        viewer._next_btn.click()
        check("다음 버튼을 한 번 더 누르면 마지막 짝으로", dialog.windowTitle() == "IMG_2.jpg", dialog.windowTitle())
        check("마지막 짝에서는 다음 콜백이 없음(다음 버튼 숨김)", viewer._on_next is None)
        check("마지막 짝에서도 이전 콜백은 있음", viewer._on_prev is not None)

        viewer._prev_btn.click()
        check("이전 버튼으로 다시 가운데 짝으로 돌아옴", dialog.windowTitle() == "IMG_1.jpg", dialog.windowTitle())


def test_single_match_has_no_nav_buttons():
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = tmp / "solo.jpg"
        mov = tmp / "solo.MOV"
        Image.new("RGB", (20, 20), color="purple").save(img)
        mov.write_bytes(b"fake")
        match = LivePhotoMatch(image_path=img, mov_path=mov)

        dialog, viewer = _build_live_photo_preview_dialog(None, [match], 0)
        check("짝이 하나뿐이면 이전 콜백도 없음", viewer._on_prev is None)
        check("짝이 하나뿐이면 다음 콜백도 없음", viewer._on_next is None)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_preview_nav_buttons_reflect_position_and_navigate()
    test_single_match_has_no_nav_buttons()
    print("OK")
