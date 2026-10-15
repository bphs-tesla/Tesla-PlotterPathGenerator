"""선 목록 → SVG 파일."""

from __future__ import annotations

from pathlib import Path

import svgwrite

from plotter.lines import Polyline


def save_svg(lines: list[Polyline], width: int, height: int, path: Path) -> None:
    drawing = svgwrite.Drawing(str(path), size=(width, height), profile="tiny", debug=False)
    d = " ".join(
        "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in line)
        for line in lines
        if len(line) >= 2
    )
    if d:
        drawing.add(drawing.path(d, fill="none", stroke="black"))
    drawing.save()
