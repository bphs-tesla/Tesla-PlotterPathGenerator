"""선 목록 타입과 그리는 순서 정렬."""

from __future__ import annotations

import numpy as np

Point = tuple[float, float]
Polyline = list[Point]


def order_lines(lines: list[Polyline], start: Point = (0.0, 0.0)) -> list[Polyline]:
    """펜을 든 채 이동하는 거리가 줄도록, 가장 가까운 끝점의 선부터 이어 붙인다."""
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return []
    starts = np.array([line[0] for line in lines], dtype=float)
    ends = np.array([line[-1] for line in lines], dtype=float)
    remaining = np.ones(len(lines), dtype=bool)
    pos = np.array(start, dtype=float)
    ordered: list[Polyline] = []
    for _ in range(len(lines)):
        d_start = np.where(remaining, np.hypot(*(starts - pos).T), np.inf)
        d_end = np.where(remaining, np.hypot(*(ends - pos).T), np.inf)
        i_start = int(np.argmin(d_start))
        i_end = int(np.argmin(d_end))
        if d_start[i_start] <= d_end[i_end]:
            index, line = i_start, list(lines[i_start])
        else:
            index, line = i_end, list(reversed(lines[i_end]))
        remaining[index] = False
        ordered.append(line)
        pos = np.array(line[-1], dtype=float)
    return ordered
