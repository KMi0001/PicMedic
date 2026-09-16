"""
gui/trash_worker.py

gui/duplicate_screen.py와 gui/similar_screen.py가 "정리 실행"에서 똑같이 쓰는
백그라운드 파일 이동 워커. 두 화면 다 원래는 이 루프를 메인 스레드에서 그대로
돌렸는데, 파일이 수백 개면(재정리 버그로 795개 사례) 진행률 표시도 없이 UI가
그대로 멈춘 것처럼 보였다 — gui/recovery_screen.py::RecoveryWorker,
gui/scan_session_window.py::_DateOrganizeWorker와 같은 이유로 QThread +
gui/common_dialogs.py::ProgressDialog 조합으로 옮겼다. 두 화면에서 똑같이
필요해져서(DESIGN.md "두 번째로 같은 게 필요해지면 공용으로 옮긴다" 원칙)
공용으로 뺐다.

ScanResult.remove()는 워커(다른 스레드) 안에서 직접 부르지 않는다 — 성공적으로
옮긴 FileInfo 목록만 finished_batch로 돌려주고, 메인 스레드(호출부)가 직접
지우게 한다(gui/scan_session_window.py::_on_date_organize_finished와 같은
원칙 — QThread 안에서 메인 스레드 객체를 직접 건드리지 않기 위함).

취소는 "현재 그룹까지는 마치고 다음 그룹부터 멈춘다" 단위로 동작한다(다른
워커들과 동일). completed_entry_indices는 to_process 안에서 "그룹의
remove_infos를 전부 시도한"(성공/실패 무관) 항목의 인덱스만 담아서, 호출부가
"이 카드/행은 이제 화면에서 지워도 되는지"를 정확히 판단할 수 있게 한다 —
취소로 인해 아예 시도조차 안 된 항목은 다음에 다시 볼 수 있게 화면에 그대로
남아야 하기 때문이다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from utils import trash


class TrashMoveWorker(QThread):
    progress = Signal(int, int, str)
    # moved_count, failed_messages, moved_infos, completed_entry_indices
    finished_batch = Signal(int, list, list, list)

    def __init__(self, to_process: list[tuple[str, list, str]], parent=None):
        super().__init__(parent)
        self.to_process = to_process
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        total = sum(len(infos) for _, infos, _ in self.to_process)
        done = 0
        moved = 0
        failed: list[str] = []
        moved_infos: list = []
        completed_entry_indices: list[int] = []

        for entry_idx, (keep_path, remove_infos, reason) in enumerate(self.to_process):
            if self._cancel_requested:
                break
            group_id = trash.new_group_id()
            for info in remove_infos:
                try:
                    trash.move_to_trash(info.path, group_id=group_id, reason=reason, kept_path=keep_path)
                    moved += 1
                    moved_infos.append(info)
                except OSError as exc:
                    failed.append(f"{Path(info.path).name} ({exc})")
                done += 1
                self.progress.emit(done, total, Path(info.path).name)
            completed_entry_indices.append(entry_idx)

        # move_to_trash()는 매 파일마다 디스크에 쓰지 않고 메모리에 모아둔다
        # (utils/trash.py — 대량 배치에서 매니페스트를 매번 다시 쓰면 갈수록
        # 느려지는 문제, 2026-09-17 실사용 리포트로 발견). 배치가 끝나면(취소로
        # 중간에 멈췄어도) 반드시 여기서 실제로 디스크에 써야 한다.
        trash.flush_trash_manifests()

        self.finished_batch.emit(moved, failed, moved_infos, completed_entry_indices)
