import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from plotter.config import Config
from plotter.processing import ProcessingError, preprocess, process, smooth_edges, to_pbm

CFG = Config()
TOOLS_INSTALLED = Path(CFG.potrace_path).exists() and Path(CFG.inkscape_path).exists()


def test_preprocess_returns_binary_of_same_size():
    rng = np.random.default_rng(0)
    gray = rng.integers(0, 256, size=(72, 128), dtype=np.uint8)
    binary = preprocess(gray)
    assert binary.shape == gray.shape
    assert set(np.unique(binary)) <= {0, 255}


def test_to_pbm_uses_actual_size():
    binary = np.full((720, 1280), 255, np.uint8)
    data = to_pbm(binary)
    assert data.startswith(b"P4\n1280 720\n")
    assert len(data) == len(b"P4\n1280 720\n") + 720 * 1280 // 8


def test_to_pbm_pads_rows_and_marks_black_as_one():
    binary = np.full((2, 10), 255, np.uint8)
    binary[0, 0] = 0  # 첫 줄 첫 픽셀만 검정
    data = to_pbm(binary)
    header = b"P4\n10 2\n"
    body = data[len(header):]
    assert data.startswith(header)
    assert len(body) == 2 * 2  # 10픽셀 → 줄마다 2바이트
    assert body == bytes([0b10000000, 0, 0, 0])


def test_missing_potrace_is_reported():
    cfg = replace(CFG, potrace_path="C:/definitely/not/here/potrace.exe")
    with pytest.raises(ProcessingError, match="potrace"):
        smooth_edges(np.full((16, 16), 255, np.uint8), cfg)


def test_failing_potrace_reports_exit_code():
    # python은 -o 옵션을 모르므로 0이 아닌 코드로 끝난다
    cfg = replace(CFG, potrace_path=sys.executable)
    with pytest.raises(ProcessingError, match="potrace 실패"):
        smooth_edges(np.full((16, 16), 255, np.uint8), cfg)


def test_process_rejects_color_image():
    with pytest.raises(ProcessingError, match="흑백"):
        process(np.zeros((10, 10, 3), np.uint8), CFG)


@pytest.mark.skipif(not TOOLS_INSTALLED, reason="potrace/Inkscape가 설치되어 있지 않음")
def test_process_end_to_end_on_non_640_image():
    gray = np.full((240, 320), 255, np.uint8)
    gray[60:180, 80:240] = 30  # 어두운 사각형
    lines = process(gray, CFG)
    assert lines
    for line in lines:
        for x, y in line:
            assert 0 <= x <= 320 and 0 <= y <= 240
