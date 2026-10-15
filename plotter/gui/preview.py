"""numpy 이미지와 선 목록을 QImage로 바꾼다."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from plotter.lines import Polyline


def gray_to_qimage(gray: np.ndarray) -> QImage:
    gray = np.ascontiguousarray(gray)
    h, w = gray.shape
    # copy(): numpy 버퍼가 사라져도 QImage가 유효하도록 데이터를 복사한다
    return QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8).copy()


def render_lines(lines: list[Polyline], width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("black"), 1))
    for line in lines:
        if len(line) >= 2:
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in line]))
    painter.end()
    return image
