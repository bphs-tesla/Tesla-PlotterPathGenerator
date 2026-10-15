"""흑백 이미지를 밝기에 따라 사선으로 해칭한다.

hatched (https://github.com/abey79/hatched, MIT License)의 _build_hatch를
shapely 2에서 동작하도록 옮긴 것이다.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import LinearRing, MultiLineString, Polygon
from skimage import measure

from plotter.lines import Polyline


def _diagonal_lines(delta: float, offset: float, w: int, h: int, angle: float) -> list[list[tuple[float, float]]]:
    angle = angle % 180
    rad = math.radians(angle)
    lines = []
    if angle == 90:
        for i in np.arange(offset, w + 1, delta):
            lines.append([(i, 0), (i, h)])
    elif angle == 0:
        for j in np.arange(offset, h + 1, delta):
            lines.append([(0, j), (w, j)])
    elif angle < 90:
        for i in np.arange(offset, h / math.tan(rad) + w + 1, delta):
            j = abs(i * math.tan(rad))
            start = (i, 0) if i <= w else (w, (i - w) * j / i)
            stop = (0, j) if j <= h else ((j - h) * i / j, h)
            lines.append([start, stop])
    else:
        for i in np.arange(h / math.tan(rad) + offset, w + 1, delta):
            j = abs((w - i) * math.tan(math.pi - rad))
            start = (i, 0) if i >= 0 else (0, -i * j / (w - i))
            stop = (w - (j - h) * (w - i) / j, h) if j >= h else (w, j)
            lines.append([start, stop])
    return lines


def _bright_mask(contours: list[np.ndarray]) -> Polygon | None:
    """등고선으로 '레벨보다 밝은 영역' 다각형을 만든다. 등고선이 없으면 None."""
    mask = None
    for points in contours:
        if len(points) < 4:
            continue
        ring = LinearRing(points[:, [1, 0]])
        if mask is None:
            mask = Polygon(ring)
        elif ring.is_ccw:
            mask = mask.union(Polygon(ring).buffer(0.5))
        else:
            mask = mask.difference(Polygon(ring).buffer(-0.5))
    return mask


def hatch_image(img: np.ndarray, pitch: float, levels: tuple[int, ...], angle: float) -> list[Polyline]:
    h, w = img.shape
    n = len(levels)

    # 가장자리를 0으로 둘러싸 등고선이 닫힌 도형이 되게 한다
    padded = np.zeros((h + 2, w + 2))
    padded[1:-1, 1:-1] = img
    masks = [_bright_mask(measure.find_contours(padded, level)) for level in levels][::-1]

    # 레벨마다 간격을 달리해 선이 서로 끼워지게 한다
    delta = [2 ** (n - 1)] + [2 ** (n - i) for i in range(1, n)]
    offset = [0] + [2 ** (n - i - 1) for i in range(1, n)]
    if angle % 180 != 0:
        pitch /= math.sin(math.radians(angle % 180))

    frame = Polygon([(3, 3), (w - 6, 3), (w - 6, h - 6), (3, h - 6)])
    result: list[Polyline] = []
    for i in range(n):
        lines = MultiLineString(_diagonal_lines(delta[i] * pitch, offset[i] * pitch, w, h, angle))
        if masks[i] is not None:
            lines = lines.difference(masks[i])
        merged = shapely.line_merge(lines.intersection(frame))
        for geom in getattr(merged, "geoms", [merged]):
            if geom.geom_type == "LineString" and not geom.is_empty:
                result.append([(float(x), float(y)) for x, y in geom.coords])
    return result
