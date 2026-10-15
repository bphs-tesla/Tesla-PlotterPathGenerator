"""픽셀 좌표 선 목록 → GRBL용 G-code."""

from __future__ import annotations

from pathlib import Path

from plotter.config import Config
from plotter.lines import Polyline, order_lines


def to_mm(lines: list[Polyline], width: int, height: int, cfg: Config) -> list[Polyline]:
    """비율을 유지해 작업 영역에 맞추고, y축을 뒤집는다 (플로터 원점은 왼쪽 아래)."""
    scale = min(cfg.work_width_mm / width, cfg.work_height_mm / height)

    def clamp(value: float, limit: float) -> float:
        return min(max(value, 0.0), limit)

    return [
        [(clamp(x * scale, cfg.work_width_mm), clamp((height - y) * scale, cfg.work_height_mm)) for x, y in line]
        for line in lines
    ]


def generate(lines: list[Polyline], width: int, height: int, cfg: Config) -> list[str]:
    dwell = [f"G4 P{cfg.pen_delay_s:g}"] if cfg.pen_delay_s > 0 else []
    commands = ["G21", "G90", cfg.pen_up, *dwell]
    for line in order_lines(to_mm(lines, width, height, cfg)):
        x, y = line[0]
        commands.append(f"G0 X{x:.2f} Y{y:.2f}")
        commands += [cfg.pen_down, *dwell]
        for i, (x, y) in enumerate(line[1:]):
            feed = f" F{cfg.feed_rate:g}" if i == 0 else ""
            commands.append(f"G1 X{x:.2f} Y{y:.2f}{feed}")
        commands += [cfg.pen_up, *dwell]
    commands.append("G0 X0 Y0")
    return commands


def save_gcode(commands: list[str], path: Path) -> None:
    path.write_text("\n".join(commands) + "\n", encoding="utf-8")
