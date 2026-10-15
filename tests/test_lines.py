import time

import numpy as np

from plotter.lines import order_lines


def test_picks_nearest_line_first():
    far = [(100.0, 100.0), (110.0, 100.0)]
    near = [(1.0, 0.0), (5.0, 0.0)]
    assert order_lines([far, near]) == [near, far]


def test_reverses_line_when_end_is_closer():
    line = [(50.0, 0.0), (1.0, 0.0)]
    assert order_lines([line]) == [[(1.0, 0.0), (50.0, 0.0)]]


def test_continues_from_end_of_previous_line():
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(100.0, 0.0), (90.0, 0.0)]
    c = [(11.0, 0.0), (20.0, 0.0)]
    assert order_lines([a, b, c]) == [a, c, [(90.0, 0.0), (100.0, 0.0)]]


def test_drops_lines_with_fewer_than_two_points():
    assert order_lines([[(1.0, 1.0)], []]) == []


def test_empty_input():
    assert order_lines([]) == []


def test_keeps_every_line_and_is_fast_enough():
    rng = np.random.default_rng(1)
    lines = [[tuple(map(float, rng.random(2) * 200)), tuple(map(float, rng.random(2) * 200))] for _ in range(5000)]
    started = time.perf_counter()
    ordered = order_lines(lines)
    assert time.perf_counter() - started < 10
    assert len(ordered) == 5000
    assert sorted(map(sorted, ordered)) == sorted(map(sorted, lines))
