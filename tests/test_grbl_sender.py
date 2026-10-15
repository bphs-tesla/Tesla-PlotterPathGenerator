import threading
import time
from collections import deque

import pytest
import serial

from plotter.grbl_sender import GrblError, GrblSender, connect

BANNER = b"Grbl 1.1h ['$' for help]\r\n"


class FakeGrbl:
    """GRBL처럼 줄마다 ok를 돌려주는 가짜 시리얼 포트."""

    def __init__(self, *, banner=False, error_on=None, silent=False, answers_reset=True):
        self.writes: list[bytes] = []
        self._replies = deque([BANNER] if banner else [])
        self.error_on = error_on
        self.silent = silent
        self.answers_reset = answers_reset
        self.lines_received = 0
        self.on_line = None
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"\x18":
            if self.answers_reset:
                self._replies.append(BANNER)
            return 1
        if data in (b"!", b"~"):
            return 1
        self.lines_received += 1
        if self.on_line:
            self.on_line(self.lines_received)
        if not self.silent:
            self._replies.append(b"error:20\r\n" if self.error_on == self.lines_received else b"ok\r\n")
        return len(data)

    def readline(self) -> bytes:
        if self._replies:
            return self._replies.popleft()
        time.sleep(0.001)
        return b""

    def close(self):
        self.closed = True


def make_sender(port, **kwargs):
    kwargs.setdefault("hold_settle_s", 0)
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
    assert tail == [b"!", b"\x18", b"M5\n"]


def test_stop_request_aborts_and_lifts_pen():
    port = FakeGrbl()
    sender = make_sender(port)
    port.on_line = lambda n: sender.request_stop() if n == 2 else None
    assert sender.stream(["G21", "G90", "G1 X1"]) is False
    assert port.writes == [b"G21\n", b"G90\n", b"!", b"\x18", b"M5\n"]


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
    assert port.writes[-3:] == [b"!", b"\x18", b"M5\n"]
    assert b"G90\n" not in port.writes


def test_silent_device_times_out():
    port = FakeGrbl(silent=True)
    with pytest.raises(GrblError, match="1번째 줄 'G21'.*응답이 없습니다"):
        make_sender(port, response_timeout_s=0.1).stream(["G21"])


def test_pause_suspends_response_timeout():
    port = FakeGrbl(silent=True)
    sender = make_sender(port, response_timeout_s=0.1)
    port.on_line = lambda n: sender.pause() if n == 1 else None
    result = {}
    thread = threading.Thread(target=lambda: result.update(value=sender.stream(["G21"])))
    thread.start()
    time.sleep(0.4)
    assert thread.is_alive()  # 일시정지 중이라 시간 초과가 나지 않는다
    sender.request_stop()
    thread.join(timeout=5)
    assert result == {"value": False}


def test_disconnect_raises_grbl_error():
    class Unplugged(FakeGrbl):
        def write(self, data):
            raise serial.SerialException("device disconnected")

    with pytest.raises(GrblError, match="끊겼습니다"):
        make_sender(Unplugged()).stream(["G21"])


def test_connect_accepts_banner():
    port = FakeGrbl(banner=True)
    assert connect("COM9", 115200, timeout_s=0.5, serial_factory=lambda name, baud, timeout: port) is port
    assert port.writes == []


def test_connect_resets_when_banner_missing():
    port = FakeGrbl(banner=False)
    assert connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, timeout: port) is port
    assert port.writes == [b"\x18"]


def test_connect_fails_without_banner():
    port = FakeGrbl(banner=False, answers_reset=False)
    started = time.monotonic()
    with pytest.raises(GrblError, match="COM9.*GRBL 응답이 없습니다"):
        connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, timeout: port)
    assert time.monotonic() - started < 2
    assert port.closed


def test_connect_reports_unopenable_port():
    def factory(name, baud, timeout):
        raise serial.SerialException("access denied")

    with pytest.raises(GrblError, match="COM9.*열 수 없습니다"):
        connect("COM9", 115200, serial_factory=factory)
