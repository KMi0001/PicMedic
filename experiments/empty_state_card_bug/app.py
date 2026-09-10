"""
experiments/empty_state_card_bug/app.py

"유사 사진/중복 사진이 없을 때 카드형태 버튼이 세로로 늘어난다"는 리포트를
재현하기 위한 진단용 스크립트. 실제 화면 클래스(OrganizeHubScreen/
DuplicateScreen/SimilarScreen)를 그대로 띄우고 빈 ScanResult를 넣은 뒤
QWidget.grab()으로 저장한다 — 목업이 아니라 실제 화면. 화면이 다른 창에
가려질 걱정이 없게 grab()을 쓴다(화면 좌표 캡처가 아니라 위젯 자체 렌더링).

사용법: python experiments/empty_state_card_bug/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from gui import theme
from gui.duplicate_screen import DuplicateScreen
from gui.organize_hub_screen import OrganizeHubScreen
from gui.similar_screen import SimilarScreen
from models.file_info import FileInfo, FileStatus
from models.scan_result import ScanResult

OUT_DIR = Path(__file__).resolve().parent


def _grab(widget, name: str, size=(1100, 750)) -> None:
    widget.resize(*size)
    widget.show()
    app.processEvents()
    app.processEvents()
    pixmap = widget.grab()
    out = OUT_DIR / name
    pixmap.save(str(out))
    print(f"saved: {out}")
    widget.hide()


app = QApplication(sys.argv)
app.setStyleSheet(theme.get_stylesheet())  # 실제 앱은 MainWindow/ScanSessionWindow가 이걸 적용함

empty_result = ScanResult()

# "유사/중복 사진이 없는 경우"를 정확히 재현하려면 진단 전 빈 상태(files=[])가
# 아니라, 진단은 끝났지만(파일은 있음) 중복/유사만 0건인 상태여야 한다.
no_dupes_result = ScanResult()
for i in range(2):
    no_dupes_result.add(
        FileInfo(
            path=f"C:/fake/photo_{i}.jpg",
            filename=f"photo_{i}.jpg",
            extension=".jpg",
            file_size=1_000_000 + i,
            content_hash=f"hash_{i}",
            status=FileStatus.NORMAL,
            readable=True,
        )
    )

hub = OrganizeHubScreen()
hub.set_result(empty_result)
_grab(hub, "hub_never_scanned.png")

hub2 = OrganizeHubScreen()
hub2.set_result(no_dupes_result)
_grab(hub2, "hub_zero_duplicates.png")

dup = DuplicateScreen()
dup.set_result(no_dupes_result)
_grab(dup, "duplicate_empty.png", size=(950, 750))

sim = SimilarScreen()
sim.set_result(no_dupes_result)
_grab(sim, "similar_empty.png", size=(950, 750))

print("DONE")
