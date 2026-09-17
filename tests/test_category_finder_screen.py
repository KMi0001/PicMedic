"""
gui/category_finder_screen.py 테스트

2026-09-18 사용자 요청: "정리_동물친구들~풍경사진 상세 화면에도 미리보기
보여주자" — 예전엔 이 화면(카테고리별 "찾기" 결과 목록)에 미리보기가 아예
없어서, 행을 확인하려면 더블클릭/우클릭으로 다른 화면(전체 상세보기)으로
넘어가야 했다. 표 옆에 gui/result_screen.py와 같은 인라인 미리보기
(ImageViewer)를 추가하고, 행을 선택(클릭)하면 바로 갱신되게 했다 — 이
테스트가 그 배선을 고정한다.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PIL import Image
from PySide6.QtWidgets import QApplication

from gui.category_finder_screen import CategoryFinderScreen
from models.file_info import FileInfo, FileStatus, RecoveryPossibility


def test_category_finder_inline_preview_updates_on_row_selection():
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        cat_path = Path(tmp) / "cat.jpg"
        dog_path = Path(tmp) / "dog.jpg"
        Image.new("RGB", (40, 30), color="orange").save(cat_path)
        Image.new("RGB", (40, 30), color="brown").save(dog_path)

        cat_info = FileInfo(
            path=str(cat_path), filename="cat.jpg", extension=".jpg",
            status=FileStatus.NORMAL, recoverable=RecoveryPossibility.NOT_RECOVERABLE,
        )
        dog_info = FileInfo(
            path=str(dog_path), filename="dog.jpg", extension=".jpg",
            status=FileStatus.NORMAL, recoverable=RecoveryPossibility.NOT_RECOVERABLE,
        )

        screen = CategoryFinderScreen("animal")
        check("인라인 뷰어가 존재함", hasattr(screen, "inline_viewer"))
        check("행이 없을 때는 미리보기가 비어있음", screen.inline_viewer._pixmap_item is None)

        screen._render_matches([(cat_info, 0.9), (dog_info, 0.8)])
        check("표에 2행이 채워짐", screen.table.rowCount() == 2)

        screen.table.selectRow(0)
        check("첫 행 선택 시 미리보기가 로드됨", screen.inline_viewer._pixmap_item is not None)

        screen.table.selectRow(1)
        check("둘째 행 선택으로 바꿔도 미리보기가 갱신됨(예외 없이 새로 로드)", screen.inline_viewer._pixmap_item is not None)


if __name__ == "__main__":  # pytest 없이 이 파일 하나만 돌려보고 싶을 때
    test_category_finder_inline_preview_updates_on_row_selection()
    print("OK")
