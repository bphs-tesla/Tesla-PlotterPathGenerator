"""이미지 처리와 GRBL 전송을 GUI 스레드 밖에서 실행한다."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

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
