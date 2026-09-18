"""app.py 화면들을 PNG로 저장 (사용자에게 보여주기 위한 1회성 캡처 스크립트)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

sys.path.insert(0, str(Path(__file__).parent))
from app import (  # noqa: E402
    SAMPLE_FILES,
    STYLESHEET,
    MockHomeScreen,
    MockOrganizeResultScreen,
    MockOrganizeSettingsScreen,
    MockResultScreen,
    RenameDialog,
    build_organize_dialog,
)

OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent


def _grab(widget, path: Path) -> None:
    # QDialog는 내용에 맞춰 크기를 다시 계산해야 하지만(팝업마다 내용이 다름),
    # QMainWindow는 이미 resize()로 명시적 크기를 정해뒀으므로 adjustSize()가
    # 그걸 내용물의 최소 크기로 덮어써버리면 안 된다(플레이스홀더만 있는
    # 메인 화면이 찌그러지는 문제).
    if isinstance(widget, QDialog):
        widget.adjustSize()
    widget.show()
    app = QApplication.instance()
    app.processEvents()
    app.processEvents()
    widget.grab().save(str(path))


def main() -> None:
    app = QApplication(sys.argv[:1])
    app.setStyleSheet(STYLESHEET)

    # 1) 검사 결과 화면 — "확장자 변환" + "이름일괄변환" 나란히
    window = MockResultScreen()
    window.show()
    app.processEvents()
    window.grab().save(str(OUT_DIR / "1_result_screen.png"))

    # 2) 이름변경 다이얼로그 — 직접입력
    for i, cb in enumerate(window._checkboxes):
        cb.setChecked(SAMPLE_FILES[i][2] == "2026-08-12")
    same_group_selection = window._selected_files()

    dialog_manual = RenameDialog(window, same_group_selection)
    _grab(dialog_manual, OUT_DIR / "2_dialog_manual.png")
    dialog_manual.close()

    # 3) 이름변경 다이얼로그 — 자동입력
    dialog_auto = RenameDialog(window, same_group_selection, start_auto=True)
    _grab(dialog_auto, OUT_DIR / "3_dialog_auto.png")
    dialog_auto.close()

    # 4) 날짜그룹 섞여서 선택 -> 자동입력 비활성화
    for cb in window._checkboxes:
        cb.setChecked(True)
    mixed_selection = window._selected_files()
    dialog_mixed = RenameDialog(window, mixed_selection)
    _grab(dialog_mixed, OUT_DIR / "4_dialog_mixed_group.png")
    dialog_mixed.close()

    # 5) 홈 화면 — 새 "이름 일괄변환" 카드
    home = MockHomeScreen()
    _grab(home, OUT_DIR / "5_home_screen.png")
    home.close()

    # 6) 정리 결과 화면(중복 사진 예시) — 하단에 "이름일괄변환" 추가 (이전 방향, 참고용)
    organize = MockOrganizeResultScreen()
    _grab(organize, OUT_DIR / "6_organize_result_screen.png")
    organize.close()

    # 7) 날짜별 정리 메인 화면 — 설정 카드 없이 목록 + "정리하기" 버튼만
    settings_screen = MockOrganizeSettingsScreen()
    _grab(settings_screen, OUT_DIR / "7_organize_main_screen.png")

    # 8) "정리하기" 팝업 — 기본값(원래 이름 유지)
    dialog_default = build_organize_dialog(settings_screen)
    _grab(dialog_default, OUT_DIR / "8_organize_dialog_default.png")
    dialog_default.close()

    # 9) 같은 팝업 — "새 이름으로 변경" 선택(인라인 2행 펼쳐짐)
    dialog_rename = build_organize_dialog(settings_screen)
    dialog_rename._rename_radio.setChecked(True)
    _grab(dialog_rename, OUT_DIR / "9_organize_dialog_rename.png")
    dialog_rename.close()

    settings_screen.close()

    print("saved to", OUT_DIR)


if __name__ == "__main__":
    main()
