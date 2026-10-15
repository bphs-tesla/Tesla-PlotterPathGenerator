"""선 목록 타입. 모든 단계가 list[Polyline]을 주고받는다."""

from __future__ import annotations

Point = tuple[float, float]
Polyline = list[Point]
