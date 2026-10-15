import time

import numpy as np

from plotter.hatching import hatch_image

LEVELS = (20, 100, 180)


def all_points(lines):
    return [p for line in lines for p in line]


def test_white_image_has_no_lines():
    assert hatch_image(np.full((120, 160), 255, np.uint8), 1.0, LEVELS, 45.0) == []


def test_black_image_is_fully_hatched():
    lines = hatch_image(np.zeros((120, 160), np.uint8), 1.0, LEVELS, 45.0)
    assert len(lines) > 50
    assert all(len(line) >= 2 for line in lines)


def test_lines_stay_inside_frame_for_non_square_image():
    h, w = 90, 200
    lines = hatch_image(np.zeros((h, w), np.uint8), 2.0, LEVELS, 45.0)
    for x, y in all_points(lines):
        assert 3 - 1e-6 <= x <= w - 6 + 1e-6
        assert 3 - 1e-6 <= y <= h - 6 + 1e-6


def test_only_dark_side_of_gradient_is_hatched():
    w = 255
    gradient = np.tile(np.arange(w, dtype=np.uint8), (100, 1))  # 왼쪽이 어둡다
    lines = hatch_image(gradient, 1.0, LEVELS, 45.0)
    assert lines
    # 밝기 180인 x=180 오른쪽(더 밝은 곳)에는 선이 없어야 한다
    # (등고선은 테두리를 1픽셀 덧댄 좌표라 몇 픽셀 여유를 둔다)
    assert max(x for x, _ in all_points(lines)) <= 185


def test_darker_means_more_ink():
    def ink(value):
        lines = hatch_image(np.full((100, 100), value, np.uint8), 1.0, LEVELS, 45.0)
        return sum(
            np.hypot(x2 - x1, y2 - y1)
            for line in lines
            for (x1, y1), (x2, y2) in zip(line, line[1:])
        )

    assert ink(10) > ink(60) > ink(140) > ink(250) == 0


def test_vertical_and_horizontal_angles_work():
    img = np.zeros((60, 80), np.uint8)
    for angle in (0.0, 90.0, 135.0):
        assert hatch_image(img, 2.0, LEVELS, angle)


def test_returns_plain_float_tuples():
    lines = hatch_image(np.zeros((40, 40), np.uint8), 2.0, LEVELS, 45.0)
    x, y = lines[0][0]
    assert type(x) is float and type(y) is float


def test_noisy_webcam_frame_is_hatched_quickly():
    # 센서 노이즈가 있으면 작은 등고선이 수천 개 생긴다. 하나씩 합치면 수십 초가 걸렸다
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:480, 0:640]
    base = 128 + 100 * np.sin(xx / 60) * np.cos(yy / 45)
    img = (base + rng.normal(0, 3, base.shape)).clip(0, 255).astype(np.uint8)
    started = time.perf_counter()
    lines = hatch_image(img, 1.0, LEVELS, 45.0)
    assert time.perf_counter() - started < 5
    assert lines
