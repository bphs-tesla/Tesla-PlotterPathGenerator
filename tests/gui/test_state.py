import pytest

from plotter.gui.state import AppState, Controls, controls_for


def controls(state, camera_ready=True, port_connected=True, has_lines=True):
    return controls_for(state, camera_ready=camera_ready, port_connected=port_connected, has_lines=has_lines)


def test_live_allows_capture_and_device_selection():
    assert controls(AppState.LIVE) == Controls(
        select_camera=True, select_port=True, capture=True, retake=False,
        send=False, pause=False, resume=False, stop=False,
    )


def test_live_without_camera_cannot_capture():
    assert controls(AppState.LIVE, camera_ready=False).capture is False


def test_processing_disables_everything_but_port():
    c = controls(AppState.PROCESSING)
    assert (c.select_camera, c.capture, c.retake, c.send, c.pause, c.resume, c.stop) == (False,) * 7
    assert c.select_port is True


def test_review_allows_send_only_when_connected_with_lines():
    assert controls(AppState.REVIEW).send is True
    assert controls(AppState.REVIEW, port_connected=False).send is False
    assert controls(AppState.REVIEW, has_lines=False).send is False
    assert controls(AppState.REVIEW).retake is True
    assert controls(AppState.REVIEW).select_camera is False


@pytest.mark.parametrize("state", [AppState.SENDING, AppState.PAUSED])
def test_drawing_locks_port_and_allows_stop(state):
    c = controls(state)
    assert c.stop is True
    assert c.select_port is False
    assert (c.capture, c.retake, c.send) == (False, False, False)


def test_pause_and_resume_are_exclusive():
    assert (controls(AppState.SENDING).pause, controls(AppState.SENDING).resume) == (True, False)
    assert (controls(AppState.PAUSED).pause, controls(AppState.PAUSED).resume) == (False, True)
