import threading
import time
from collections import deque

import pytest
import serial

from plotter.grbl_sender import GrblError, GrblSender, connect

BANNER = b"Grbl 1.1h ['$' for help]\r\n"


class FakeGrbl:
    """GRBL처럼 줄마다 ok를 돌려주는 가짜 시리얼 포트."""

    def __init__(self, *, banner=False, error_on=None, silent=False, answers_reset=True,
                 decel_polls=0, alarm_on_reset=False, ok_delay_s=0.0):
        self.writes: list[bytes] = []
        self._replies = deque([BANNER] if banner else [])
        self._delayed: list[tuple[float, bytes]] = []
        self.error_on = error_on
        self.silent = silent
        self.answers_reset = answers_reset
        self.decel_polls = decel_polls  # 멈춤(!) 뒤 감속이 끝나기 전까지 Hold:1로 답하는 횟수
        self.alarm_on_reset = alarm_on_reset  # 움직이는 중 리셋한 것처럼 알람 상태가 된다
        self.ok_delay_s = ok_delay_s  # 긴 선을 그리는 동안 ok가 늦게 오는 것을 흉내 낸다
        self.lines_received = 0
        self.on_line = None
        self.closed = False
        self._held = False
        self._alarm = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"\x18":
            self._held = False
            if self.answers_reset:
                if self.alarm_on_reset:
                    self._alarm = True
                    self._replies.append(b"ALARM:3\r\n")
                self._replies.append(BANNER)
            return 1
        if data == b"!":
            self._held = True
            return 1
        if data == b"~":
            self._held = False
            return 1
        if data == b"?":
            if not self.silent:
                if self._held and self.decel_polls > 0:
                    self.decel_polls -= 1
                    self._replies.append(b"<Hold:1|MPos:0.000,0.000,0.000>\r\n")
                else:
                    state = b"Hold:0" if self._held else b"Run" if self._delayed else b"Idle"
                    self._replies.append(b"<" + state + b"|MPos:0.000,0.000,0.000>\r\n")
            return 1
        self.lines_received += 1
        if self.on_line:
            self.on_line(self.lines_received)
        if not self.silent:
            if self._alarm:
                reply = b"error:9\r\n"
            elif self.error_on == self.lines_received:
                reply = b"error:20\r\n"
            else:
                reply = b"ok\r\n"
            if self.ok_delay_s:
                self._delayed.append((time.monotonic() + self.ok_delay_s, reply))
            else:
                self._replies.append(reply)
        return len(data)

    def readline(self) -> bytes:
        now = time.monotonic()
        while self._delayed and self._delayed[0][0] <= now:
            self._replies.append(self._delayed.pop(0)[1])
        if self._replies:
            return self._replies.popleft()
        time.sleep(0.001)
        return b""

    def close(self):
        self.closed = True


def make_sender(port, **kwargs):
    return GrblSender(port, "M5", **kwargs)


def test_stream_sends_all_lines_then_syncs_and_reports_progress():
    port = FakeGrbl()
    progress = []
    assert make_sender(port).stream(["G21", "G90", "G1 X1 Y1"], lambda d, t: progress.append((d, t))) is True
    assert port.writes == [b"G21\n", b"G90\n", b"G1 X1 Y1\n", b"G4 P0\n"]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_stream_ignores_status_messages():
    port = FakeGrbl()
    port._replies.append(b"[MSG:Caution: Unlocked]\r\n")
    assert make_sender(port).stream(["G21"]) is True


def test_grbl_error_raises_with_line_number_and_lifts_pen():
    port = FakeGrbl(error_on=2)
    with pytest.raises(GrblError, match="2번째 줄 'G90'.*error:20"):
        make_sender(port).stream(["G21", "G90", "G1 X1"])
    assert b"G1 X1\n" not in port.writes
    tail = port.writes[port.writes.index(b"G90\n") + 1:]
    assert tail == [b"!", b"?", b"\x18", b"M5\n"]


def test_stop_request_aborts_and_lifts_pen():
    port = FakeGrbl()
    sender = make_sender(port)
    port.on_line = lambda n: sender.request_stop() if n == 2 else None
    assert sender.stream(["G21", "G90", "G1 X1"]) is False
    assert port.writes == [b"G21\n", b"G90\n", b"!", b"?", b"\x18", b"M5\n"]


def test_pause_and_resume_send_realtime_commands():
    port = FakeGrbl()
    sender = make_sender(port)
    sender.pause()
    sender.resume()
    assert port.writes == [b"!", b"~"]


def test_stop_while_paused():
    port = FakeGrbl()
    sender = make_sender(port)

    def on_line(n):
        if n == 1:
            sender.pause()
            sender.request_stop()

    port.on_line = on_line
    assert sender.stream(["G21", "G90"]) is False
    assert port.writes[-4:] == [b"!", b"?", b"\x18", b"M5\n"]
    assert b"G90\n" not in port.writes


def test_silent_device_times_out():
    port = FakeGrbl(silent=True)
    with pytest.raises(GrblError, match="1번째 줄 'G21'.*응답이 없습니다"):
        make_sender(port, response_timeout_s=0.1, hold_timeout_s=0.1).stream(["G21"])


def test_pause_suspends_response_timeout():
    port = FakeGrbl(silent=True)
    sender = make_sender(port, response_timeout_s=0.1)
    port.on_line = lambda n: sender.pause() if n == 1 else None
    result = {}
    thread = threading.Thread(target=lambda: result.update(value=sender.stream(["G21"])))
    thread.start()
    time.sleep(0.4)
    assert thread.is_alive()  # 일시정지 중이라 시간 초과가 나지 않는다
    port.silent = False  # 정지 순서(상태 확인, 리셋, 펜 올림)에는 응답한다
    sender.request_stop()
    thread.join(timeout=5)
    assert result == {"value": False}


def test_stop_waits_for_motion_to_halt_before_reset():
    # 감속이 끝나기 전에 리셋하면 GRBL이 위치를 잃고 알람 상태가 된다
    port = FakeGrbl(decel_polls=3)
    sender = make_sender(port)
    port.on_line = lambda n: sender.request_stop() if n == 1 else None
    assert sender.stream(["G1 X100"]) is False
    hold = port.writes.index(b"!")
    reset = port.writes.index(b"\x18")
    assert port.writes[hold + 1:reset] == [b"?"] * 4  # Hold:1 세 번, Hold:0 한 번
    assert port.writes[-1] == b"M5\n"


def test_alarm_after_reset_is_reported_instead_of_claiming_pen_up():
    port = FakeGrbl(alarm_on_reset=True)
    sender = make_sender(port)
    port.on_line = lambda n: sender.request_stop() if n == 1 else None
    with pytest.raises(GrblError, match="펜을 올리지 못했.*error:9"):
        sender.stream(["G1 X100"])


def test_long_stroke_does_not_time_out_while_grbl_reports_status():
    # G4/M5는 앞선 동작이 끝나야 ok가 온다. 긴 선을 느리게 그리면 응답 시간보다 오래 걸린다
    port = FakeGrbl(ok_delay_s=0.5)
    sender = make_sender(port, response_timeout_s=0.2, status_interval_s=0.05)
    assert sender.stream(["G1 X200 F300"]) is True
    assert b"?" in port.writes


def test_disconnect_raises_grbl_error():
    class Unplugged(FakeGrbl):
        def write(self, data):
            raise serial.SerialException("device disconnected")

    with pytest.raises(GrblError, match="끊겼습니다"):
        make_sender(Unplugged()).stream(["G21"])


def test_connect_accepts_banner():
    port = FakeGrbl(banner=True)
    assert connect("COM9", 115200, timeout_s=0.5, serial_factory=lambda name, baud, **kwargs: port) is port
    assert port.writes == []


def test_connect_resets_when_banner_missing():
    port = FakeGrbl(banner=False)
    assert connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, **kwargs: port) is port
    assert port.writes == [b"\x18"]


def test_connect_fails_without_banner():
    port = FakeGrbl(banner=False, answers_reset=False)
    started = time.monotonic()
    with pytest.raises(GrblError, match="COM9.*GRBL 응답이 없습니다"):
        connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, **kwargs: port)
    assert time.monotonic() - started < 2
    assert port.closed


def test_connect_reports_unopenable_port():
    def factory(name, baud, **kwargs):
        raise serial.SerialException("access denied")

    with pytest.raises(GrblError, match="COM9.*열 수 없습니다"):
        connect("COM9", 115200, serial_factory=factory)


def test_connect_gives_up_on_port_whose_writes_never_complete():
    # 상대 장치가 없는 블루투스 가상 포트(COM6 등)는 쓰기가 끝나지 않는다.
    # 쓰기 제한 시간이 없으면 리셋 바이트를 쓰는 순간 프로그램이 영원히 멈춘다
    class DeadBluetoothPort(FakeGrbl):
        def __init__(self, write_timeout):
            super().__init__(banner=False)
            self.write_timeout = write_timeout

        def write(self, data):
            if self.write_timeout is None:
                raise AssertionError("쓰기 제한 시간이 없어 실제 포트라면 영원히 멈춘다")
            raise serial.SerialTimeoutException("Write timeout")

    opened = []

    def factory(name, baud, timeout=None, write_timeout=None):
        opened.append(DeadBluetoothPort(write_timeout))
        return opened[0]

    with pytest.raises(GrblError, match="COM6.*GRBL 응답이 없습니다"):
        connect("COM6", 115200, timeout_s=0.1, serial_factory=factory)
    assert opened[0].closed
