"""흑백 프레임 → 이진화 → potrace/Inkscape로 외곽 다듬기 → 해칭."""

from __future__ import annotations

import subprocess

import cv2
import numpy as np

from plotter.config import Config
from plotter.hatching import hatch_image
from plotter.lines import Polyline

_TOOL_TIMEOUT_S = 60


class ProcessingError(Exception):
    """이미지 처리 실패. 메시지는 사용자에게 그대로 보여준다."""


def preprocess(gray: np.ndarray) -> np.ndarray:
    # 노이즈 제거
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    # 적응형 이진화
    binary = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 19, 5)
    # 선 두께 약간 보정
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def to_pbm(binary: np.ndarray) -> bytes:
    h, w = binary.shape
    bits = np.packbits((binary == 0).astype(np.uint8), axis=1)
    return f"P4\n{w} {h}\n".encode() + bits.tobytes()


def _run(name: str, cmd: list[str], data: bytes) -> bytes:
    try:
        result = subprocess.run(cmd, input=data, capture_output=True, timeout=_TOOL_TIMEOUT_S, check=False)
    except FileNotFoundError as exc:
        raise ProcessingError(f"{name}을(를) 찾을 수 없습니다: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(f"{name}이(가) {_TOOL_TIMEOUT_S}초 안에 끝나지 않았습니다") from exc
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()[:200]
        raise ProcessingError(f"{name} 실패 (코드 {result.returncode}): {detail}")
    return result.stdout


def smooth_edges(binary: np.ndarray, cfg: Config) -> np.ndarray:
    svg = _run(
        "potrace",
        [cfg.potrace_path, "-s", "-o", "-", "--turdsize", "2", "--alphamax", "1",
         "--opttolerance", "0.2", "--unit", "10"],
        to_pbm(binary),
    )
    png = _run(
        "Inkscape",
        [cfg.inkscape_path, "--pipe", "--export-type=png", "--export-background=white", "--export-filename=-"],
        svg,
    )
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ProcessingError("Inkscape 출력 이미지를 읽을 수 없습니다")
    h, w = binary.shape
    return cv2.resize(img, (w, h))


def process(gray: np.ndarray, cfg: Config) -> list[Polyline]:
    if gray.ndim != 2:
        raise ProcessingError(f"흑백 이미지가 필요합니다 (받은 모양: {gray.shape})")
    edges = smooth_edges(preprocess(gray), cfg)
    blended = cv2.addWeighted(edges, 0.55, gray, 0.8, 1)
    return hatch_image(blended, cfg.hatch_pitch, cfg.hatch_levels, cfg.hatch_angle)
