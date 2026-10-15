"""GRBL로 G-code를 한 줄씩 보내고 ok를 기다린다 (send-response 방식)."""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Callable

import serial
from serial.tools import list_ports

_SYNC = "G4 P0"  # GRBL은 버퍼가 다 비워진 뒤에 이 명령에 ok를 보낸다
_FEED_HOLD = b"!"
_CYCLE_START = b"~"
_SOFT_RESET = b"\x18"


class GrblError(Exception):
    """GRBL 통신 실패. 메시지는 사용자에게 그대로 보여준다."""


def available_ports() -> list[str]:
    return sorted(port.device for port in list_ports.comports())


def _read_text(port) -> str:
    try:
        return port.readline().decode(errors="replace").strip()
    except serial.SerialException as exc:
        raise GrblError(f"시리얼 연결이 끊겼습니다: {exc}") from exc


def _wait_for_banner(port, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _read_text(port).startswith("Grbl"):
            return True
    return False


def connect(port_name: str, baud: int, timeout_s: float = 3.0, serial_factory=serial.Serial):
    try:
        port = serial_factory(port_name, baud, timeout=0.2)
    except serial.SerialException as exc:
        raise GrblError(f"{port_name}을(를) 열 수 없습니다: {exc}") from exc
    try:
        if _wait_for_banner(port, timeout_s):
            return port
        port.write(_SOFT_RESET)
        if _wait_for_banner(port, timeout_s):
            return port
    except (GrblError, serial.SerialException):
        pass
    port.close()
    raise GrblError(f"{port_name}에서 GRBL 응답이 없습니다. 포트와 펌웨어를 확인하세요")


class GrblSender:
    def __init__(self, port, pen_up: str, response_timeout_s: float = 30.0, hold_settle_s: float = 0.5):
        self._port = port
        self._pen_up = pen_up
        self._response_timeout_s = response_timeout_s
        self._hold_settle_s = hold_settle_s
        # RLock: 같은 스레드가 쓰는 도중 다시 pause()를 불러도 멈추지 않게 한다
        self._write_lock = threading.RLock()
        self._paused = threading.Event()
        self._stop = threading.Event()

    def pause(self) -> None:
        self._paused.set()
        self._write(_FEED_HOLD)

    def resume(self) -> None:
        self._paused.clear()
        self._write(_CYCLE_START)

    def request_stop(self) -> None:
        self._stop.set()

    def stream(self, commands: list[str], on_progress: Callable[[int, int], None] = lambda done, total: None) -> bool:
        self._stop.clear()
        self._paused.clear()
        total = len(commands)
        try:
            for index, command in enumerate(commands, start=1):
                if not self._send_and_wait(index, command):
                    self._abort()
                    return False
                on_progress(index, total)
            if not self._send_and_wait(total + 1, _SYNC):
                self._abort()
                return False
            return True
        except GrblError:
            with contextlib.suppress(GrblError):
                self._abort()
            raise

    def _write(self, data: bytes) -> None:
        try:
            with self._write_lock:
                self._port.write(data)
        except serial.SerialException as exc:
            raise GrblError(f"시리얼 연결이 끊겼습니다: {exc}") from exc

    def _send_and_wait(self, index: int, command: str) -> bool:
        """ok를 받으면 True, 정지 요청이면 False. error/ALARM/응답 없음은 GrblError."""
        if self._stop.is_set():
            return False
        self._write(command.encode("ascii") + b"\n")
        deadline = time.monotonic() + self._response_timeout_s
        while True:
            if self._stop.is_set():
                return False
            reply = _read_text(self._port)
            if reply == "ok":
                return True
            if reply.startswith(("error", "ALARM")):
                raise GrblError(f"{index}번째 줄 '{command}'에서 GRBL 오류: {reply}")
            if reply:
                continue  # [MSG:...] 같은 상태 메시지는 무시
            if self._paused.is_set():
                deadline = time.monotonic() + self._response_timeout_s
            elif time.monotonic() > deadline:
                raise GrblError(f"{index}번째 줄 '{command}'에 GRBL 응답이 없습니다")

    def _abort(self) -> None:
        """멈춤 → 리셋(버퍼 비움) → 펜 올림. 멈춘 뒤 리셋하면 위치를 잃지 않는다."""
        self._write(_FEED_HOLD)
        time.sleep(self._hold_settle_s)
        self._write(_SOFT_RESET)
        _wait_for_banner(self._port, 2.0)
        self._paused.clear()
        self._write(self._pen_up.encode("ascii") + b"\n")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if _read_text(self._port) == "ok":
                break
