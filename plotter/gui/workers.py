"""이미지 처리와 GRBL 전송을 GUI 스레드 밖에서 실행한다."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from plotter import grbl_sender
from plotter.config import Config
from plotter.grbl_sender import GrblError, GrblSender
from plotter.processing import ProcessingError, process


class ProcessThread(QThread):
    succeeded = pyqtSignal(object)  # list[Polyline]
    failed = pyqtSignal(str)

    def __init__(self, gray: np.ndarray, cfg: Config, parent=None):
        super().__init__(parent)
        self._gray = gray
        self._cfg = cfg

    def run(self) -> None:
        try:
            lines = process(self._gray, self._cfg)
        except ProcessingError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # 스레드 밖으로 예외가 나가면 조용히 사라지므로 모두 알린다
            self.failed.emit(f"이미지 처리 중 예상치 못한 오류: {exc}")
            return
        self.succeeded.emit(lines)


class SendThread(QThread):
    progress = pyqtSignal(int, int)
    completed = pyqtSignal(bool)  # True: 끝까지 그림, False: 정지됨
    failed = pyqtSignal(str)

    def __init__(self, sender: GrblSender, commands: list[str], parent=None):
        super().__init__(parent)
        self._sender = sender
        self._commands = commands

    def run(self) -> None:
        try:
            finished = self._sender.stream(self._commands, self.progress.emit)
        except GrblError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"전송 중 예상치 못한 오류: {exc}")
            return
        self.completed.emit(finished)


class ConnectThread(QThread):
    """GRBL 연결. 블루투스 포트는 여는 데만 10초 넘게 걸릴 수 있어 GUI 스레드에서 하지 않는다."""

    connected = pyqtSignal(object)  # 열린 시리얼 포트
    failed = pyqtSignal(str)

    def __init__(self, port_name: str, baud: int, parent=None):
        super().__init__(parent)
        self._port_name = port_name
        self._baud = baud
        self.port = None  # 창을 닫을 때 시그널이 처리되지 않았어도 포트를 닫을 수 있게 남겨 둔다

    def run(self) -> None:
        try:
            self.port = grbl_sender.connect(self._port_name, self._baud)
        except GrblError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"연결 중 예상치 못한 오류: {exc}")
            return
        self.connected.emit(self.port)
