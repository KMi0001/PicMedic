"""
gui/duplicate_screen.py 테스트

2026-09-17 실사용 리포트: "폴더 단위" 카드에서 폴더명을 눌러 남길 폴더를
골랐다고 생각했는데, 실제로 정리를 실행하니 반대 폴더가 지워졌다는 버그를
재현한다. 원인: 폴더명 칸(QToolButton)은 펼침/접힘(미리보기)만 하고 실제
라디오 선택은 안 바꿨음 — 라디오는 화면 왼쪽의 작은 원인데 사람들은 자연히
폴더명을 눌러서 "골랐다"고 생각한다. 폴더명을 누르면 라디오도 같이
선택되도록 고쳤고, 이 테스트가 그 동작을 고정한다. 개별 그룹 카드의 파일
경로 클릭도 같은 문제라 같이 고쳤다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import check

from PySide6.QtWidgets import QApplication, QToolButton

from gui.duplicate_screen import DuplicateScreen
from models.file_info import FileInfo, FileStatus, RecoveryPossibility
from models.scan_result import ScanResult


def _info(path: str) -> FileInfo:
    p = Path(path)
    return FileInfo(
        path=path,
        filename=p.name,
        extension=p.suffix,
        status=FileStatus.NORMAL,
        recoverable=RecoveryPossibility.RECOVERABLE,
        content_hash="same",
    )


def test_cluster_folder_click_selects_radio():
    app = QApplication.instance() or QApplication(sys.argv)

    folder_a = r"C:\fake\클라우드베리백업\kmi3735\폴더\2018.02.06 선미졸업"
    folder_b = r"C:\fake\선미졸업식\116___02"

    result = ScanResult()
    result.add(_info(str(Path(folder_a) / "IMG_0001.jpg")))
    result.add(_info(str(Path(folder_b) / "IMG_0001.jpg")))

    screen = DuplicateScreen()
    screen.set_result(result)

    check("폴더 단위 조합 카드가 1개 생성됨", len(screen._cluster_entries) == 1, len(screen._cluster_entries))
    entry = screen._cluster_entries[0]

    check("건너뛰기가 기본 선택(추천 없음)", entry.skip_radio.isChecked() is True)
    for r in entry.radios:
        check("폴더 라디오는 초기엔 선택 안 됨", r.isChecked() is False)

    table = entry.card
    target_row = None
    for row in range(table.rowCount()):
        widget = table.cellWidget(row, 1)
        if isinstance(widget, QToolButton) and folder_b in widget.text():
            target_row = row
            break
    check("folder_b 폴더명 버튼을 표에서 찾음", target_row is not None)

    # 사용자가 실제로 하는 행동: 폴더명(토글 버튼)을 클릭 — 라디오를 직접
    # 누르는 게 아니라 폴더명 자체를 눌러서 "이걸 남기겠다"고 고른다.
    table.cellWidget(target_row, 1).click()

    check("폴더명 클릭 후 건너뛰기 선택 해제됨", entry.skip_radio.isChecked() is False)

    keep_folder = next(
        (folder for folder, radio in zip(entry.folder_options, entry.radios) if radio.isChecked()),
        None,
    )
    check(
        "폴더명을 클릭한 바로 그 폴더가 실제로 keep_folder로 계산됨",
        keep_folder is not None and str(keep_folder) == folder_b,
        f"실제={keep_folder}",
    )

    # "건너뛰기" 칸도 같은 이유로 고쳤다 — 폴더 라디오를 선택한 뒤 다시
    # "건너뛰기" 칸을 클릭하면 skip_radio로 되돌아가야 한다.
    table.cellClicked.emit(0, 1)
    check("건너뛰기 칸 클릭 후 skip_radio가 선택됨", entry.skip_radio.isChecked() is True)


def test_manual_card_path_click_selects_radio():
    """폴더로 안 갈리는(같은 폴더 안 중복) 그룹의 개별 카드도 같은 문제라
    같이 고쳤다 — 파일 경로 레이블을 누르면 미리보기만 열리고 라디오는
    그대로였음."""
    app = QApplication.instance() or QApplication(sys.argv)

    result = ScanResult()
    result.add(_info(r"C:\fake\같은폴더\a.jpg"))
    result.add(_info(r"C:\fake\같은폴더\b.jpg"))

    screen = DuplicateScreen()
    screen.set_result(result)

    check("폴더로 못 가르는 그룹은 manual로 감", len(screen._manual_entries) == 1, len(screen._manual_entries))
    entry = screen._manual_entries[0]
    check("추천 없어 건너뛰기가 기본", entry.skip_radio.isChecked() is True)

    # _build_group_card는 radios를 group과 같은 순서로 만든다.
    target_info = result.files[1]
    target_radio = entry.radios[1]
    check("두 번째 라디오는 초기엔 선택 안 됨", target_radio.isChecked() is False)

    # path_label(_ClickableLabel)을 찾아 클릭 — QHBoxLayout 안에 radio, path_label 순.
    from gui.duplicate_screen import _ClickableLabel

    clicked = False

    labels = entry.card.findChildren(_ClickableLabel)
    check("파일 경로 레이블 2개를 찾음", len(labels) == 2, len(labels))
    for label in labels:
        if target_info.path in label.text():
            label.clicked.emit()
            clicked = True
            break
    check("대상 파일의 경로 레이블을 클릭함", clicked)

    check("경로 클릭 후 그 파일의 라디오가 선택됨", target_radio.isChecked() is True)
    check("건너뛰기 선택 해제됨", entry.skip_radio.isChecked() is False)
