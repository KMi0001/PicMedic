"""
utils/single_instance.py

앱 중복 실행 방지 (2026-09-20, 사용자 요청) — PicMedic을 한 번 더 실행하면 새 앱을
띄우는 대신 이미 실행 중인 앱의 창을 앞으로 가져온다. 팝업 안내 없이 조용히 처리한다.

작업 자동 저장(core/session_store.py)이 폴더마다 파일 하나에 저장하기 때문에 앱이
둘이면 같은 폴더를 검사했을 때 서로의 저장본을 덮어쓸 수 있다는 이유도 있다.

구현은 Qt의 QLocalServer/QLocalSocket(Windows는 named pipe, macOS는 unix 소켓)만 쓴다
— OS별 분기 없음. 이름에 사용자 이름을 넣어서 같은 PC의 다른 계정(빠른 사용자
전환)끼리는 서로 막지 않는다.
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 500


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - 사용자 이름을 못 구해도 실행은 돼야 한다
        user = "user"
    return f"PicMedic-single-instance-{user}"


class SingleInstance(QObject):
    """acquire()가 True면 이 프로세스가 첫 번째 실행이고, False면 이미 실행 중인 앱에
    "창을 앞으로 가져와 달라"는 신호를 보낸 뒤라서 호출한 쪽은 바로 종료하면 된다.
    첫 번째 실행에서는 다른 실행이 신호를 보낼 때마다 activated가 발생한다."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = _server_name()
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        if self._notify_existing():
            return False

        # 접속이 안 되는데 이름이 남아 있는 경우(앱이 비정상 종료한 뒤의 찌꺼기)를
        # 치우고 새로 연다. Windows named pipe는 프로세스가 죽으면 저절로 사라져서
        # 이 호출이 아무 일도 안 한다.
        QLocalServer.removeServer(self._name)
        server = QLocalServer(self)
        if not server.listen(self._name):
            # 거의 동시에 두 번 실행해서 방금 다른 쪽이 먼저 열었을 수 있다 — 한 번 더
            # 접속해 보고, 그래도 안 되면 중복 방지를 포기하고 그냥 실행한다(앱이
            # 아예 안 뜨는 것보다 낫다).
            return not self._notify_existing()
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def _notify_existing(self) -> bool:
        """이미 실행 중인 앱이 있으면 신호를 보내고 True."""
        socket = QLocalSocket(self)
        socket.connectToServer(self._name)
        if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            socket.abort()
            return False
        socket.write(b"show")
        socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activated.emit()
