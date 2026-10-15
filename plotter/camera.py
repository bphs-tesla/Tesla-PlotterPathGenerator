"""웹캠 탐색, 열기, 흑백 프레임 읽기."""

from __future__ import annotations

import cv2
import numpy as np


class CameraError(Exception):
    """카메라를 열 수 없을 때 발생한다."""


def list_cameras(max_index: int = 6, capture_factory=cv2.VideoCapture) -> list[int]:
    found = []
    for index in range(max_index):
        capture = capture_factory(index, cv2.CAP_DSHOW)
        try:
            if capture.isOpened():
                found.append(index)
        finally:
            capture.release()
    return found


def open_camera(index: int, capture_factory=cv2.VideoCapture):
    capture = capture_factory(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        raise CameraError(f"카메라 {index}을(를) 열 수 없습니다")
    return capture


def read_gray(capture) -> np.ndarray | None:
    ok, frame = capture.read()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
