from collections import deque

import numpy as np
import pytest

from plotter.maze import CELL_PX, generate_maze, maze_arrows, maze_drawing, maze_to_lines


def unit_edges(lines):
    """선 목록을 기둥(짝수 칸) 사이 한 칸짜리 벽 조각 집합으로 나눈다."""
    edges = set()
    for line in lines:
        for (x1, y1), (x2, y2) in zip(line, line[1:]):
            assert x1 == x2 or y1 == y2, "미로 벽은 가로나 세로여야 한다"
            c1, r1, c2, r2 = (round(v / CELL_PX) * 2 for v in (x1, y1, x2, y2))
            if r1 == r2:
                for c in range(min(c1, c2), max(c1, c2), 2):
                    edges.add((r1, c + 1))
            else:
                for r in range(min(r1, r2), max(r1, r2), 2):
                    edges.add((r + 1, c1))
    return edges


def wall_edges(grid):
    """격자에서 기둥 사이에 놓인 벽 칸(행이나 열 중 하나만 홀수)의 위치."""
    rows, cols = grid.shape
    return {
        (r, c)
        for r in range(rows)
        for c in range(cols)
        if grid[r, c] == 1 and (r % 2) != (c % 2)
    }


def test_generate_maze_has_requested_size_and_two_openings():
    grid = generate_maze(7, 5, seed=1)
    assert grid.shape == (11, 15)
    border = np.concatenate([grid[0, :], grid[-1, :], grid[:, 0], grid[:, -1]])
    # 테두리에서 입구와 출구 두 곳만 뚫려 있다 (모서리는 두 번 세지 않도록 기둥은 항상 벽)
    assert int((border == 0).sum()) == 2


def test_same_seed_gives_same_maze():
    assert np.array_equal(generate_maze(6, 4, seed=7), generate_maze(6, 4, seed=7))


def test_too_small_maze_is_rejected():
    with pytest.raises(ValueError, match="3"):
        generate_maze(2, 5)


def test_entrance_and_exit_are_connected():
    grid = generate_maze(9, 6, seed=3)
    rows, cols = grid.shape
    openings = [
        (r, c) for r in range(rows) for c in range(cols)
        if grid[r, c] == 0 and (r in (0, rows - 1) or c in (0, cols - 1))
    ]
    start, goal = openings
    seen, queue = {start}, deque([start])
    while queue:
        r, c = queue.popleft()
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= nr < rows and 0 <= nc < cols and grid[nr, nc] == 0 and (nr, nc) not in seen:
                seen.add((nr, nc))
                queue.append((nr, nc))
    assert goal in seen


def test_maze_to_lines_for_single_row_of_two_cells():
    grid = np.array([
        [1, 1, 1, 1, 1],
        [1, 0, 1, 0, 1],
        [1, 1, 1, 1, 1],
    ], np.int8)
    s = float(CELL_PX)
    lines = maze_to_lines(grid)
    assert sorted(map(tuple, lines)) == sorted([
        ((0.0, 0.0), (2 * s, 0.0)),   # 위쪽 벽 (한 줄로 합쳐짐)
        ((0.0, s), (2 * s, s)),       # 아래쪽 벽
        ((0.0, 0.0), (0.0, s)),       # 왼쪽 벽
        ((s, 0.0), (s, s)),           # 가운데 벽
        ((2 * s, 0.0), (2 * s, s)),   # 오른쪽 벽
    ])


def test_lines_cover_every_wall_and_no_opening():
    grid = generate_maze(12, 8, seed=5)
    assert unit_edges(maze_to_lines(grid)) == wall_edges(grid)


def test_lines_fit_inside_drawing_size():
    grid = generate_maze(10, 4, seed=2)
    width, height = 10 * CELL_PX, 4 * CELL_PX
    for line in maze_to_lines(grid):
        for x, y in line:
            assert 0 <= x <= width and 0 <= y <= height
            assert type(x) is float and type(y) is float


def shaft_and_head(arrow_lines):
    """화살표 하나 = 몸통 [꼬리, 끝] + 촉 [한쪽, 끝, 다른쪽]."""
    shaft, head = arrow_lines
    assert len(shaft) == 2 and len(head) == 3
    assert head[1] == shaft[1]  # 촉은 화살표 끝에 붙는다
    return shaft


def test_arrows_point_into_entrance_and_out_of_exit_on_side_walls():
    s = float(CELL_PX)
    grid = np.array([
        [1, 1, 1, 1, 1],
        [0, 0, 1, 0, 0],  # 왼쪽 벽과 오른쪽 벽이 뚫려 있다
        [1, 1, 1, 1, 1],
    ], np.int8)
    arrows = maze_arrows(grid)
    assert len(arrows) == 4
    (tail, tip) = shaft_and_head(arrows[:2])  # 출발: 왼쪽 바깥에서 안으로
    assert tail[1] == tip[1] == s / 2
    assert tail[0] < tip[0] <= 0
    (tail, tip) = shaft_and_head(arrows[2:])  # 도착: 오른쪽 벽에서 밖으로
    assert tail[1] == tip[1] == s / 2
    assert 2 * s <= tail[0] < tip[0]


def test_arrows_on_top_and_bottom_walls():
    s = float(CELL_PX)
    grid = np.array([
        [1, 0, 1, 1, 1],  # 위쪽 벽 왼쪽 칸이 뚫림 → 출발
        [1, 0, 0, 0, 1],
        [1, 1, 1, 0, 1],  # 아래쪽 벽 오른쪽 칸이 뚫림 → 도착
    ], np.int8)
    arrows = maze_arrows(grid)
    (tail, tip) = shaft_and_head(arrows[:2])
    assert tail[0] == tip[0] == s / 2
    assert tail[1] < tip[1] <= 0  # 위에서 아래로 들어간다
    (tail, tip) = shaft_and_head(arrows[2:])
    assert tail[0] == tip[0] == 1.5 * s
    assert s <= tail[1] < tip[1]  # 아래로 나간다


def test_drawing_has_margin_for_arrows_and_keeps_everything_inside():
    grid = generate_maze(8, 5, seed=4)
    lines, width, height = maze_drawing(grid)
    assert (width, height) == ((8 + 2) * CELL_PX, (5 + 2) * CELL_PX)
    walls = maze_to_lines(grid)
    assert len(lines) == len(walls) + 4
    # 벽은 여백만큼 옮겨진다
    assert lines[0] == [(x + CELL_PX, y + CELL_PX) for x, y in walls[0]]
    for line in lines:
        for x, y in line:
            assert 0 <= x <= width and 0 <= y <= height
