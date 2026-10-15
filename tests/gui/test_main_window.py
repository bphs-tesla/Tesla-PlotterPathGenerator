import re
import threading
import time

import pytest
from PyQt6.QtCore import QSettings

from plotter import camera, grbl_sender
from plotter.config import Config
from plotter.gui.main_window import MainWindow
from plotter.gui.state import AppState


def finish_connect(window, qapp):
    """백그라운드 연결이 끝날 때까지 기다리고 결과 시그널을 처리한다."""
    worker = getattr(window, "_connect_worker", None)
    if worker is not None:
        assert worker.wait(5000)
    qapp.processEvents()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "list_cameras", lambda *a, **k: [])
    monkeypatch.setattr(grbl_sender, "available_ports", lambda: ["COM7"])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Config(), tmp_path / "output", settings)  # 아직 없는 폴더
    yield w
    w.close()


def test_starts_live_without_camera(window):
    assert window._state is AppState.LIVE
    assert not window._capture_button.isEnabled()
    assert "카메라를 찾을 수 없습니다" in window._status.text()
    assert window._port_combo.currentText() == "COM7"


def test_processed_result_is_saved_and_reviewed(window, tmp_path):
    window._image_size = (640, 480)
    window._on_processed([[(10.0, 10.0), (100.0, 100.0)]])
    assert window._state is AppState.REVIEW
    # output 폴더를 만들고, 촬영 시각이 들어간 같은 이름으로 svg와 gcode를 저장한다
    svgs = list((tmp_path / "output").glob("*.svg"))
    gcodes = list((tmp_path / "output").glob("*.gcode"))
    assert len(svgs) == 1 and len(gcodes) == 1
    assert re.fullmatch(r"output-\d{8}-\d{6}", svgs[0].stem)
    assert gcodes[0].stem == svgs[0].stem
    assert gcodes[0].read_text(encoding="utf-8").startswith("G21\nG90\n")
    assert svgs[0].name in window._status.text()
    assert window._retake_button.isEnabled()
    assert not window._send_button.isEnabled()  # 포트가 연결되지 않음


def test_each_capture_keeps_its_own_files(window, tmp_path, monkeypatch):
    times = iter(["20261016-090000", "20261016-090105"])
    monkeypatch.setattr(window, "_timestamp", lambda: next(times))
    window._image_size = (640, 480)
    window._on_processed([[(10.0, 10.0), (100.0, 100.0)]])
    window._retake()
    window._on_processed([[(20.0, 20.0), (200.0, 200.0)]])
    names = sorted(p.name for p in (tmp_path / "output").iterdir())
    assert names == [
        "output-20261016-090000.gcode", "output-20261016-090000.svg",
        "output-20261016-090105.gcode", "output-20261016-090105.svg",
    ]


def test_empty_result_disables_send(window):
    window._image_size = (640, 480)
    window._serial = object()  # 연결된 것처럼
    window._on_processed([])
    assert window._state is AppState.REVIEW
    assert not window._send_button.isEnabled()
    assert "그릴 선이 없습니다" in window._status.text()
    window._serial = None


def test_processing_failure_returns_to_live(window):
    window._state = AppState.PROCESSING
    window._on_process_failed("potrace을(를) 찾을 수 없습니다: C:/potrace.exe")
    assert window._state is AppState.LIVE
    assert "potrace" in window._status.text()


def test_connect_failure_is_shown(window, monkeypatch, qapp):
    def fail(name, baud):
        raise grbl_sender.GrblError(f"{name}에서 GRBL 응답이 없습니다. 포트와 펌웨어를 확인하세요")

    monkeypatch.setattr(grbl_sender, "connect", fail)
    window._toggle_connection()
    finish_connect(window, qapp)
    assert window._serial is None
    assert "GRBL 응답이 없습니다" in window._status.text()
    assert window._connect_button.text() == "연결"
    assert window._connect_button.isEnabled()


def test_connect_runs_in_background_without_freezing_gui(window, monkeypatch, qapp):
    # 블루투스 포트는 여는 데만 13초가 걸린다. 그동안 창이 멈추면 안 된다
    release = threading.Event()

    class Port:
        def close(self):
            pass

    port = Port()

    def slow_connect(name, baud):
        release.wait(2)
        return port

    monkeypatch.setattr(grbl_sender, "connect", slow_connect)
    started = time.monotonic()
    window._toggle_connection()
    assert time.monotonic() - started < 0.5
    assert "연결 중" in window._status.text()
    assert not window._connect_button.isEnabled()
    assert not window._port_combo.isEnabled()

    release.set()
    finish_connect(window, qapp)
    assert window._serial is port
    assert window._connect_button.text() == "연결 해제"
    assert window._connect_button.isEnabled()
