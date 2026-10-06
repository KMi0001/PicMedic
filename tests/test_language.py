"""Language switching exercises real screens and preserves active editing state."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QLabel, QTableWidgetItem

from gui import i18n
from gui.common_dialogs import ProgressDialog
from gui.help_dialog import HelpDialog
from gui.main_window import MainWindow
from gui.recovery_screen import RecoveryScreen, QUALITY_PRESETS
from gui.result_screen import ResultScreen
from models.file_info import FileInfo, FileStatus, RecoveryPossibility
from models.scan_result import ScanResult


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings_path = str(tmp_path / "language.ini")
    monkeypatch.setattr(i18n, "QSettings", lambda *_: QSettings(settings_path, QSettings.IniFormat))
    previous = i18n.get_language()
    i18n.set_language("ko")
    yield app
    i18n.set_language(previous)
    app.processEvents()


def test_footer_switches_existing_home_help_and_progress(app):
    window = MainWindow()
    home = window.home_screen
    help_dialog = HelpDialog(window)
    progress = ProgressDialog(window)
    progress.start(i18n.message("사진 변환 진행 중"))
    progress.update_progress(2, 5, "확인.jpg")
    help_dialog._stack.setCurrentIndex(2)
    home.language_buttons["en"].click()

    assert home.language_buttons["en"].isChecked()
    assert not home.language_buttons["ko"].isChecked()
    assert home.subtitle_label.text() == "Give your photos a little care"
    assert "Privacy policy" in home.privacy_link.text()
    assert "Diagnose" in window.windowTitle()
    assert help_dialog.windowTitle() == "PicMedic help"
    assert help_dialog._stack.currentIndex() == 2
    assert progress.title_label.text() == "Converting photos"
    assert progress.status_label.text() == "확인.jpg\nProcessing... (2/5)"
    assert progress.bar.value() == 40

    # Theme refresh must not reset language or privacy text.
    home._on_theme_toggled(home.theme_toggle.isChecked())
    assert "Privacy policy" in home.privacy_link.text()
    home.language_buttons["ko"].click()
    assert home.subtitle_label.text() == "사진을 치료해줄게요"
    assert progress.status_label.text() == "확인.jpg\n처리 중... (2/5)"
    progress.accept()
    help_dialog.close()
    window.close()


def test_scan_selection_and_file_identity_survive_language_switch(app, tmp_path):
    # The name intentionally equals a translated UI term: it must stay untouched.
    path = tmp_path / "확인.jpg"
    info = FileInfo(path=str(path), filename=path.name, extension=".jpg",
                    status=FileStatus.MISMATCH, recoverable=RecoveryPossibility.RECOVERABLE)
    result = ScanResult()
    result.add(info)
    screen = ResultScreen()
    screen.set_result(result)
    screen._set_all_checked(Qt.Checked)
    status_item = screen.table.item(0, 1)
    file_item = screen.table.item(0, 2)

    i18n.set_language("en")
    assert "Format mismatch" in status_item.text()
    assert file_item.text() == "확인.jpg"
    assert screen.table.horizontalHeaderItem(1).text() == "Status"
    assert screen._selected_files() == [info]
    assert info.status is FileStatus.MISMATCH
    assert info.path == str(path)
    assert screen.result is result

    i18n.set_language("ko")
    assert "형식 불일치" in status_item.text()
    assert screen._selected_files() == [info]
    screen._stop_category_scan()
    screen.close()


def test_quality_and_user_inputs_remain_stable(app):
    screen = RecoveryScreen()
    screen.quality_combo.setCurrentIndex(0)
    screen.output_edit.setText("/tmp/확인/사진")
    screen.suffix_edit.setText("정상")
    canonical = screen.quality_combo.currentData()
    quality = QUALITY_PRESETS[canonical]
    i18n.set_language("en")
    assert screen.quality_combo.currentText() == "High quality"
    assert QUALITY_PRESETS[screen.quality_combo.currentData()] == quality == 95
    assert screen.output_edit.text() == "/tmp/확인/사진"
    assert screen.suffix_edit.text() == "정상"
    i18n.set_language("ko")
    assert screen.quality_combo.currentText() == "고화질"
    screen.close()


def test_deleted_items_and_plain_user_text_do_not_get_translated(app):
    item = i18n.localized_widget(QTableWidgetItem, i18n.message("확인"))
    plain = i18n.localized_widget(QLabel, "확인")
    bound = i18n.localized_widget(QLabel, i18n.message("정상"))
    # Reusing a label for user data must remove its former translation binding.
    i18n.set_ui(bound, "text", "확인")
    disposable = i18n.localized_widget(QLabel, i18n.message("확인"))
    import shiboken6
    shiboken6.delete(disposable)
    i18n.set_language("en")
    assert item.text() == "OK"
    assert plain.text() == bound.text() == "확인"
    i18n.set_language("ko")
    assert item.text() == "확인"
    plain.close()
    bound.close()


def test_selected_language_is_restored_in_a_new_process(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(tmp_path / "config"),
               XDG_CACHE_HOME=str(tmp_path / "cache"))
    cwd = str(Path(__file__).resolve().parents[1])
    save = "from PySide6.QtWidgets import QApplication; from gui.i18n import set_language; app=QApplication([]); set_language('en')"
    load = "from PySide6.QtWidgets import QApplication; from gui.main_window import MainWindow; app=QApplication([]); w=MainWindow(); assert w.home_screen.language_buttons['en'].isChecked(); assert w.home_screen.subtitle_label.text() == 'Give your photos a little care'"
    subprocess.run([sys.executable, "-c", save], cwd=cwd, env=env, check=True, timeout=30)
    subprocess.run([sys.executable, "-c", load], cwd=cwd, env=env, check=True, timeout=30)


def test_category_and_geographic_labels_translate_without_changing_keys(app):
    from core.category_finder import CATEGORIES
    from gui.category_finder_screen import CategoryFinderScreen
    from gui.city_map_view import _CityMarker

    screen = CategoryFinderScreen("animal")
    # Category IDs and output folder names remain canonical Korean core data.
    original_title = CATEGORIES["animal"].title
    original_folder = CATEGORIES["animal"].output_folder_name
    marker = _CityMarker(10, "서울 (3)")
    i18n.set_language("en")
    assert any(label.text() == "Animals & pets" for label in screen.findChildren(QLabel))
    assert marker.label_text() == "Seoul (3)"
    assert CATEGORIES["animal"].title == original_title
    assert CATEGORIES["animal"].output_folder_name == original_folder
    screen.close()


def test_file_picker_captions_translate_but_returned_paths_do_not(app):
    captured = {}
    paths = ["/tmp/확인.jpg"]

    def picker(parent, caption, directory, file_filter):
        captured.update(caption=caption, directory=directory, file_filter=file_filter)
        return paths, file_filter

    i18n.set_language("en")
    result, _ = i18n.file_dialog(
        picker, None, i18n.message("사진 파일 선택 (여러 개 선택 가능)"), "/tmp/확인",
        i18n.message("이미지 파일 ({0});;모든 파일 (*)", "*.jpg"),
    )
    assert captured["caption"] == "Select photos (multiple selection supported)"
    assert captured["file_filter"] == "Image files (*.jpg);;All files (*)"
    assert captured["directory"] == "/tmp/확인"
    assert result is paths


def test_saved_explanation_and_error_messages_preserve_embedded_paths(app):
    explanation = "개별 그룹 정리 — '확인.jpg' 파일을 남기고 이 파일들이 이동됨"
    localized = i18n.system_message(explanation)
    i18n.set_language("en")
    assert localized.render() == "Individual group — keep '확인.jpg' and move these files"
    assert str(localized) == explanation
    assert i18n.system_message("변환 실패: /tmp/확인.jpg").render() == "Conversion failed: /tmp/확인.jpg"
