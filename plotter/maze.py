"""mazelib로 미로를 만들고 벽을 선 목록으로 바꾼다.

mazelib의 격자는 (2 × 세로칸 + 1) × (2 × 가로칸 + 1) 크기이고 1이 벽이다.
짝수 행·열이 만나는 칸이 기둥이고, 기둥 사이 칸이 벽 조각이다.
PNG를 거치지 않고 벽을 바로 직선으로 바꾸므로 펜이 벽 선만 그린다.
"""

from __future__ import annotations

from collections import deque
from enum import Enum

import numpy as np
from mazelib import Maze
from mazelib.generate.BacktrackingGenerator import BacktrackingGenerator
from mazelib.generate.HuntAndKill import HuntAndKill
from mazelib.generate.Prims import Prims

from plotter.lines import Polyline

CELL_PX = 10  # 한 칸의 크기 (픽셀). G-code에서 작업 영역에 맞춰 늘어나므로 비율만 의미가 있다
MIN_CELLS = 3  # mazelib는 3칸보다 작은 미로를 만들지 못한다
MARGIN_PX = CELL_PX  # 입구/출구 화살표를 그릴 바깥 여백

# 화살표 크기 (칸 크기에 대한 비율). 꼬리와 끝은 벽에서 바깥쪽으로 떨어진 거리다
_ARROW_NEAR = 0.15
_ARROW_FAR = 0.9
_ARROW_HEAD = 0.3


class Difficulty(Enum):
    """화면에 보이는 이름이 값이다.

    20×15칸에서 잰 평균 정답 길이(전체 칸 대비): 쉬움 11%, 보통 23%, 어려움 약 55%.
    """

    EASY = "쉬움"  # Prims: 짧은 막다른 길이 많아 한눈에 걸러진다
    NORMAL = "보통"  # HuntAndKill: 막다른 길이 길어 잘못 들어가면 오래 헤맨다
    HARD = "어려움"  # Backtracking으로 여러 개 만들어 정답이 가장 긴 것을 고른다


_HARD_CANDIDATES = 20


def _one_maze(generator) -> np.ndarray:
    maze = Maze()
    maze.generator = generator
    maze.generate()
    maze.generate_entrances(start_outer=True, end_outer=True)
    grid = np.array(maze.grid, dtype=np.int8)
    # mazelib는 입구 위치만 알려주고 벽은 그대로 두므로 직접 뚫는다
    grid[maze.start] = 0
    grid[maze.end] = 0
    return grid


def generate_maze(
    cols: int, rows: int, seed: int | None = None, difficulty: Difficulty = Difficulty.EASY
) -> np.ndarray:
    """가로 cols칸, 세로 rows칸 미로. 바깥 벽에 입구와 출구를 뚫어 돌려준다."""
    if cols < MIN_CELLS or rows < MIN_CELLS:
        raise ValueError(f"미로는 가로, 세로 모두 {MIN_CELLS}칸 이상이어야 합니다 (받은 값: {cols}×{rows})")
    Maze.set_seed(seed)  # 후보를 여러 개 만들어도 seed가 같으면 결과가 같다
    if difficulty is Difficulty.EASY:
        return _one_maze(Prims(rows, cols))
    if difficulty is Difficulty.NORMAL:
        return _one_maze(HuntAndKill(rows, cols))
    candidates = [_one_maze(BacktrackingGenerator(rows, cols)) for _ in range(_HARD_CANDIDATES)]
    return max(candidates, key=solution_length)


def solution_length(grid: np.ndarray) -> int:
    """입구에서 출구까지 가장 짧은 길이 지나는 격자 칸 수 (입구와 출구 포함)."""
    openings = _openings(grid)
    if len(openings) < 2:
        return 0
    start, goal = openings[0], openings[1]
    rows, cols = grid.shape
    distance = {start: 1}
    queue = deque([start])
    while queue:
        r, c = queue.popleft()
        if (r, c) == goal:
            return distance[goal]
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= nr < rows and 0 <= nc < cols and grid[nr, nc] == 0 and (nr, nc) not in distance:
                distance[(nr, nc)] = distance[(r, c)] + 1
                queue.append((nr, nc))
    return 0


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


def _openings(grid: np.ndarray) -> list[tuple[int, int]]:
    """바깥 벽에서 뚫린 칸. 왼쪽(같으면 위쪽)에 있는 것이 출발점이 되도록 정렬한다."""
    rows, cols = grid.shape
    found = [
        (r, c)
        for r in range(rows)
        for c in range(cols)
        if grid[r, c] == 0 and (r in (0, rows - 1) or c in (0, cols - 1))
    ]
    return sorted(found, key=lambda rc: (rc[1], rc[0]))


def _arrow(tail: tuple[float, float], tip: tuple[float, float]) -> list[Polyline]:
    """몸통 [꼬리, 끝]과 촉 [한쪽, 끝, 다른쪽] 두 선으로 된 화살표."""
    dx, dy = tip[0] - tail[0], tip[1] - tail[1]
    length = float(np.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    back = _ARROW_HEAD * CELL_PX
    side = back * 0.6
    left = (tip[0] - ux * back - uy * side, tip[1] - uy * back + ux * side)
    right = (tip[0] - ux * back + uy * side, tip[1] - uy * back - ux * side)
    return [[tail, tip], [left, tip, right]]


def maze_arrows(grid: np.ndarray) -> list[Polyline]:
    """입구 바깥에서 안쪽으로 들어가는 화살표와 출구에서 바깥으로 나가는 화살표.

    좌표는 벽 선과 같은 기준이라 미로 바깥(음수 포함)에 놓인다.
    """
    rows, cols = grid.shape
    arrows: list[Polyline] = []
    for index, (r, c) in enumerate(_openings(grid)[:2]):
        # 뚫린 벽 조각의 가운데와 바깥쪽 방향
        mid = (c * CELL_PX / 2, r * CELL_PX / 2)
        if c == 0:
            out = (-1.0, 0.0)
        elif c == cols - 1:
            out = (1.0, 0.0)
        elif r == 0:
            out = (0.0, -1.0)
        else:
            out = (0.0, 1.0)

        def at(distance: float) -> tuple[float, float]:
            return (float(mid[0] + out[0] * distance * CELL_PX), float(mid[1] + out[1] * distance * CELL_PX))

        near, far = at(_ARROW_NEAR), at(_ARROW_FAR)
        arrows += _arrow(far, near) if index == 0 else _arrow(near, far)
    return arrows


def maze_drawing(grid: np.ndarray) -> tuple[list[Polyline], int, int]:
    """벽과 화살표를 여백만큼 옮긴 선 목록과 그림 크기 (너비, 높이)."""
    rows, cols = grid.shape
    width = (cols // 2) * CELL_PX + 2 * MARGIN_PX
    height = (rows // 2) * CELL_PX + 2 * MARGIN_PX
    lines = [
        [(x + MARGIN_PX, y + MARGIN_PX) for x, y in line]
        for line in maze_to_lines(grid) + maze_arrows(grid)
    ]
    return lines, width, height
