"""
experiments/empty_state_card_bug/city_layout_check.py

city_organize_screen.py 재배치(지도|목록 + 도시별 카드 그룹화) 확인용 —
core/geocoder.py 없이 _groups/_files/_file_to_label을 직접 채워서 진짜 화면을
그대로 그려본다(목업 아님).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication

from gui import theme
from gui.city_organize_screen import CityOrganizeScreen
from models.file_info import FileInfo, FileStatus

OUT_DIR = Path(__file__).resolve().parent

app = QApplication(sys.argv)
app.setStyleSheet(theme.get_stylesheet())

screen = CityOrganizeScreen()

seoul = [
    FileInfo(
        path=f"C:/fake/seoul/img_{i}.jpg", filename=f"img_{i}.jpg", extension=".jpg",
        file_size=1_000_000, status=FileStatus.NORMAL, readable=True,
        latitude=37.5665, longitude=126.9780,
    )
    for i in range(4)
]
busan = [
    FileInfo(
        path=f"C:/fake/busan/img_{i}.jpg", filename=f"img_{i}.jpg", extension=".jpg",
        file_size=1_000_000, status=FileStatus.NORMAL, readable=True,
        latitude=35.1796, longitude=129.0756,
    )
    for i in range(3)
]

screen._groups = [("서울", seoul), ("부산", busan)]
screen._no_gps_groups = []
screen._files = seoul + busan
screen._file_to_label = {f.path: "서울" for f in seoul} | {f.path: "부산" for f in busan}
screen.content_stack.setCurrentWidget(screen.map_list_widget)
screen.organize_btn.setEnabled(True)
screen._refresh_map()
screen._refresh_region_list()

screen.resize(1150, 800)
screen.show()
app.processEvents()
app.processEvents()

out = OUT_DIR / "city_layout.png"
screen.grab().save(str(out))
print(f"saved: {out}")
