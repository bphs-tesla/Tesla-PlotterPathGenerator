import pytest
from PyQt6.QtCore import QSettings

from plotter import camera, grbl_sender
from plotter.config import Config
from plotter.gui.main_window import MainWindow
from plotter.gui.state import AppState


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "list_cameras", lambda *a, **k: [])
    monkeypatch.setattr(grbl_sender, "available_ports", lambda: ["COM7"])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Config(), tmp_path, settings)
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
    assert (tmp_path / "output.svg").exists()
    gcode = (tmp_path / "output.gcode").read_text(encoding="utf-8")
    assert gcode.startswith("G21\nG90\n")
    assert window._retake_button.isEnabled()
    assert not window._send_button.isEnabled()  # 포트가 연결되지 않음


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


def test_connect_failure_is_shown(window, monkeypatch):
    def fail(name, baud):
        raise grbl_sender.GrblError(f"{name}에서 GRBL 응답이 없습니다. 포트와 펌웨어를 확인하세요")

    monkeypatch.setattr(grbl_sender, "connect", fail)
    window._toggle_connection()
    assert window._serial is None
    assert "GRBL 응답이 없습니다" in window._status.text()
    assert window._connect_button.text() == "연결"
