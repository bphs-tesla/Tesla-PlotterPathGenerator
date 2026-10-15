import cv2
import numpy as np
import pytest

from plotter.camera import CameraError, list_cameras, open_camera, read_gray


class FakeCapture:
    released: list[int] = []

    def __init__(self, index, api, available=(0, 2), frame=None):
        self.index, self.api = index, api
        self._open = index in available
        self._frame = frame

    def isOpened(self):
        return self._open

    def read(self):
        return (self._frame is not None, self._frame)

    def release(self):
        FakeCapture.released.append(self.index)


def test_list_cameras_returns_openable_indices_and_releases_all():
    FakeCapture.released = []
    assert list_cameras(4, FakeCapture) == [0, 2]
    assert sorted(FakeCapture.released) == [0, 1, 2, 3]


def test_cameras_are_opened_with_directshow():
    seen = []

    def factory(index, api):
        seen.append(api)
        return FakeCapture(index, api)

    list_cameras(2, factory)
    open_camera(0, factory)
    assert set(seen) == {cv2.CAP_DSHOW}


def test_open_camera_fails_for_missing_device():
    with pytest.raises(CameraError, match="카메라 1"):
        open_camera(1, FakeCapture)


def test_read_gray_converts_bgr_frame():
    frame = np.zeros((4, 6, 3), np.uint8)
    frame[..., 2] = 255  # 빨강
    gray = read_gray(FakeCapture(0, 0, frame=frame))
    assert gray.shape == (4, 6)
    assert gray.dtype == np.uint8
    assert int(gray[0, 0]) == 76  # 0.299 * 255


def test_read_gray_returns_none_on_failure():
    assert read_gray(FakeCapture(0, 0, frame=None)) is None
