"""mazelib로 미로를 만들고 벽을 선 목록으로 바꾼다.

mazelib의 격자는 (2 × 세로칸 + 1) × (2 × 가로칸 + 1) 크기이고 1이 벽이다.
짝수 행·열이 만나는 칸이 기둥이고, 기둥 사이 칸이 벽 조각이다.
PNG를 거치지 않고 벽을 바로 직선으로 바꾸므로 펜이 벽 선만 그린다.
"""

from __future__ import annotations

import numpy as np
from mazelib import Maze
from mazelib.generate.Prims import Prims

from plotter.lines import Polyline

CELL_PX = 10  # 한 칸의 크기 (픽셀). G-code에서 작업 영역에 맞춰 늘어나므로 비율만 의미가 있다
MIN_CELLS = 3  # mazelib는 3칸보다 작은 미로를 만들지 못한다


def generate_maze(cols: int, rows: int, seed: int | None = None) -> np.ndarray:
    """가로 cols칸, 세로 rows칸 미로. 바깥 벽에 입구와 출구를 뚫어 돌려준다."""
    if cols < MIN_CELLS or rows < MIN_CELLS:
        raise ValueError(f"미로는 가로, 세로 모두 {MIN_CELLS}칸 이상이어야 합니다 (받은 값: {cols}×{rows})")
    maze = Maze(seed)
    maze.generator = Prims(rows, cols)
    maze.generate()
    maze.generate_entrances(start_outer=True, end_outer=True)
    grid = np.array(maze.grid, dtype=np.int8)
    # mazelib는 입구 위치만 알려주고 벽은 그대로 두므로 직접 뚫는다
    grid[maze.start] = 0
    grid[maze.end] = 0
    return grid


def maze_to_lines(grid: np.ndarray) -> list[Polyline]:
    """벽을 가로선과 세로선으로 바꾼다. 이어진 벽은 한 선으로 합쳐 펜을 덜 든다."""
    rows, cols = grid.shape
    lines: list[Polyline] = []

    def point(r: int, c: int) -> tuple[float, float]:
        return (float(c // 2 * CELL_PX), float(r // 2 * CELL_PX))

    # 가로 벽: 짝수 행에서 기둥 사이(홀수 열) 칸이 벽인 구간을 이어 붙인다
    for r in range(0, rows, 2):
        c = 1
        while c < cols:
            if grid[r, c]:
                start = c - 1
                while c < cols and grid[r, c]:
                    c += 2
                lines.append([point(r, start), point(r, c - 1)])
            c += 2

    # 세로 벽: 짝수 열에서 기둥 사이(홀수 행) 칸이 벽인 구간
    for c in range(0, cols, 2):
        r = 1
        while r < rows:
            if grid[r, c]:
                start = r - 1
                while r < rows and grid[r, c]:
                    r += 2
                lines.append([point(start, c), point(r - 1, c)])
            r += 2

    return lines
