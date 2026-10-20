"""GRBL로 G-code를 한 줄씩 보내고 ok를 기다린다 (send-response 방식)."""

from __future__ import annotations

import contextlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import serial
from serial.tools import list_ports

_SYNC = "G4 P0"  # GRBL은 버퍼가 다 비워진 뒤에 이 명령에 ok를 보낸다
_FEED_HOLD = b"!"
_CYCLE_START = b"~"
_SOFT_RESET = b"\x18"
_STATUS = b"?"
_HOLD_POLL_S = 0.2
_WRITE_TIMEOUT_S = 1.0


class GrblError(Exception):
    """GRBL 통신 실패. 메시지는 사용자에게 그대로 보여준다."""


class GrblReplyError(GrblError):
    """GRBL이 명령을 거부했다 (error:N / ALARM). 연결 자체는 살아 있다."""


@dataclass(frozen=True)
class MachineInfo:
    """아두이노가 $L로 알려 주는 작업 영역과 현재 위치 (mm, 원점 = 왼쪽 아래)."""

    width_mm: float
    height_mm: float
    limits_on: bool
    # 예전 펌웨어가 보내지 않는 값은 None
    x_mm: float | None = None
    y_mm: float | None = None
    speed_mm_min: float | None = None  # 최고 속도
    pen_up_deg: int | None = None  # 펜 올림 / 내림 서보 각도
    pen_down_deg: int | None = None


_AREA = re.compile(
    r"Area (-?[\d.]+) x (-?[\d.]+) mm, limits (\w+)"
    r"(?:, pos (-?[\d.]+),(-?[\d.]+))?(?:, speed ([\d.]+))?(?:, pen (\d+)/(\d+))?"
)


def _optional(value: str | None, kind=float):
    return kind(value) if value is not None else None


def parse_machine_info(message: str) -> MachineInfo | None:
    """[MSG:...] 안의 'Area W x H mm, limits ON, pos X,Y, speed V, pen U/D'를 읽는다. 다른 메시지면 None."""
    match = _AREA.match(message)
    if match is None:
        return None
    width, height, limits, x, y, speed, pen_up, pen_down = match.groups()
    return MachineInfo(
        float(width), float(height), limits == "ON",
        _optional(x), _optional(y), _optional(speed), _optional(pen_up, int), _optional(pen_down, int),
    )


def latest_machine_info(messages: list[str]) -> MachineInfo | None:
    for message in reversed(messages):
        info = parse_machine_info(message)
        if info is not None:
            return info
    return None


def query_machine_info(port, timeout_s: float = 2.0) -> MachineInfo | None:
    """연결 직후 $L을 보내 작업 영역을 읽는다. 답이 없으면 None."""
    port.write(b"$L\n")
    info = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        reply = _read_text(port)
        if reply.startswith("[MSG:") and reply.endswith("]"):
            info = parse_machine_info(reply[len("[MSG:"):-1]) or info
        elif reply == "ok" or reply.startswith("error"):
            break
    return info


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
        # write_timeout: 상대가 없는 블루투스 가상 포트는 쓰기가 끝나지 않아 제한 시간이 없으면 영원히 멈춘다
        port = serial_factory(port_name, baud, timeout=0.2, write_timeout=_WRITE_TIMEOUT_S)
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
    def __init__(self, port, pen_up: str, response_timeout_s: float = 30.0, hold_timeout_s: float = 10.0,
                 status_interval_s: float = 1.0):
        self._port = port
        self._pen_up = pen_up
        # 응답 시간: GRBL이 ok도 상태 보고도 보내지 않은 채 이만큼 지나면 오류
        self._response_timeout_s = response_timeout_s
        # 정지할 때 감속이 끝나기를 기다리는 최대 시간
        self._hold_timeout_s = hold_timeout_s
        # ok를 기다리는 동안 이 간격으로 상태(?)를 물어 GRBL이 살아 있는지 확인한다
        self._status_interval_s = status_interval_s
        # RLock: 같은 스레드가 쓰는 도중 다시 pause()를 불러도 멈추지 않게 한다
        self._write_lock = threading.RLock()
        self._paused = threading.Event()
        self._stop = threading.Event()
        # 마지막 stream() 동안 받은 [MSG:...]의 내용 (예: 끝 설정 뒤 작업 영역 크기)
        self.messages: list[str] = []

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
        self.messages = []
        try:
            finished = self._send_all(commands, on_progress)
        except GrblError:
            with contextlib.suppress(GrblError):
                self._abort()
            raise
        if not finished:
            self._abort()  # 펜을 올리지 못하면 GrblError
        return finished

    def _send_all(self, commands: list[str], on_progress: Callable[[int, int], None]) -> bool:
        total = len(commands)
        for index, command in enumerate(commands, start=1):
            if not self._send_and_wait(index, command):
                return False
            on_progress(index, total)
        return self._send_and_wait(total + 1, _SYNC)

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
        next_status = time.monotonic() + self._status_interval_s
        while True:
            if self._stop.is_set():
                return False
            reply = _read_text(self._port)
            if reply == "ok":
                return True
            if reply.startswith(("error", "ALARM")):
                detail = f" ({self.messages[-1]})" if self.messages else ""
                raise GrblReplyError(f"{index}번째 줄 '{command}'에서 GRBL 오류: {reply}{detail}")
            if reply.startswith("[MSG:") and reply.endswith("]"):
                self.messages.append(reply[len("[MSG:"):-1])
            now = time.monotonic()
            if reply.startswith("<") or self._paused.is_set():
                # 상태 보고가 오면 아직 그리는 중이다. G4/M5의 ok는 앞선 동작이 끝나야 온다
                deadline = now + self._response_timeout_s
            elif now > deadline:
                raise GrblError(f"{index}번째 줄 '{command}'에 GRBL 응답이 없습니다")
            if now >= next_status:
                self._write(_STATUS)
                next_status = now + self._status_interval_s
            # 그 밖의 응답은 무시

    def _wait_for_hold(self) -> None:
        """멈춤(!) 뒤 감속이 끝날 때까지(Hold:0 또는 Idle) 기다린다."""
        deadline = time.monotonic() + self._hold_timeout_s
        next_status = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_status:
                self._write(_STATUS)
                next_status = time.monotonic() + _HOLD_POLL_S
            if _read_text(self._port).startswith(("<Hold:0", "<Idle")):
                return

    def _abort(self) -> None:
        """멈춤 → 감속 끝까지 대기 → 리셋(버퍼 비움) → 펜 올림. 멈춘 뒤 리셋해야 위치를 잃지 않는다."""
        self._write(_FEED_HOLD)
        self._wait_for_hold()
        self._write(_SOFT_RESET)
        _wait_for_banner(self._port, 2.0)
        self._paused.clear()
        self._write(self._pen_up.encode("ascii") + b"\n")
        reply = ""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            reply = _read_text(self._port)
            if reply == "ok":
                return
            if reply.startswith(("error", "ALARM")):
                break
        # 리셋 뒤 알람 상태면 GRBL이 G-code를 거부한다. 위치를 잃었을 수 있으므로 알린다
        raise GrblError(
            f"정지했지만 펜을 올리지 못했습니다 (GRBL 응답: {reply or '없음'}). "
            "GRBL 알람을 풀고($X 또는 $H) 펜 위치를 확인하세요"
        )
