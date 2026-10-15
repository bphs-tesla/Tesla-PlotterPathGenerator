import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from plotter.config import Config
from plotter.processing import (
    PROJECT_ROOT,
    ProcessingError,
    preprocess,
    process,
    render_svg,
    smooth_edges,
    to_pbm,
    tool_path,
)

CFG = Config()
TOOLS_INSTALLED = tool_path(CFG.potrace_path).exists()

# potrace -s 출력과 같은 모양: pt 단위 크기, 뒤집힌 좌표계 transform, 상대 곡선 경로
POTRACE_STYLE_SVG = b"""<?xml version="1.0" standalone="no"?>
<svg version="1.0" xmlns="http://www.w3.org/2000/svg" width="64.000000pt" height="48.000000pt"
 viewBox="0 0 64.000000 48.000000" preserveAspectRatio="xMidYMid meet">
<g transform="translate(0.000000,48.000000) scale(0.100000,-0.100000)" fill="#000000" stroke="none">
<path d="M0 0 l320 0 l0 480 l-320 0 z"/>
</g>
</svg>
"""

FAKE_POTRACE = '''
import sys
header = sys.stdin.buffer.read().split(b"\\n")
w, h = header[1].split()
w, h = int(w), int(h)
# 왼쪽 절반을 채운 SVG를 potrace처럼 출력한다
sys.stdout.write(f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}pt" height="{h}pt" viewBox="0 0 {w} {h}">
<g transform="translate(0,{h}) scale(0.1,-0.1)" fill="#000000" stroke="none">
<path d="M0 0 l{w * 5} 0 l0 {h * 10} l-{w * 5} 0 z"/></g></svg>""")
'''


def fake_potrace(tmp_path: Path) -> str:
    script = tmp_path / "fake_potrace.py"
    script.write_text(FAKE_POTRACE, encoding="utf-8")
    launcher = tmp_path / "fake_potrace.cmd"
    launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    return str(launcher)


def test_render_svg_draws_potrace_output_without_inkscape():
    img = render_svg(POTRACE_STYLE_SVG, 64, 48)
    assert img.shape == (48, 64)
    assert img.dtype == np.uint8
    assert img[24, 10] < 64  # 왼쪽 절반은 검정
    assert img[24, 50] > 192  # 오른쪽 절반은 흰 배경


def test_render_svg_fits_requested_size():
    # 미리보기와 같은 크기로 그려야 원본 사진과 섞을 수 있다
    img = render_svg(POTRACE_STYLE_SVG, 128, 96)
    assert img.shape == (96, 128)
    assert img[48, 20] < 64 and img[48, 100] > 192


def test_invalid_svg_is_reported():
    with pytest.raises(ProcessingError, match="SVG"):
        render_svg(b"not an svg", 10, 10)


def test_smooth_edges_uses_only_potrace(tmp_path):
    cfg = replace(CFG, potrace_path=fake_potrace(tmp_path))
    edges = smooth_edges(np.full((30, 40), 255, np.uint8), cfg)
    assert edges.shape == (30, 40)
    assert edges[15, 5] < 64 and edges[15, 35] > 192


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


@pytest.mark.skipif(not TOOLS_INSTALLED, reason="potrace가 설치되어 있지 않음")
def test_process_end_to_end_on_non_640_image():
    gray = np.full((240, 320), 255, np.uint8)
    gray[60:180, 80:240] = 30  # 어두운 사각형
    lines = process(gray, CFG)
    assert lines
    for line in lines:
        for x, y in line:
            assert 0 <= x <= 320 and 0 <= y <= 240


def test_relative_tool_path_is_resolved_from_project_folder():
    # 상대 경로는 실행한 위치가 아니라 프로젝트 폴더를 기준으로 찾는다
    assert tool_path("./potrace/potrace.exe") == PROJECT_ROOT / "potrace" / "potrace.exe"
    assert tool_path("C:/potrace.exe") == Path("C:/potrace.exe")


@pytest.mark.skipif(not TOOLS_INSTALLED, reason="potrace가 설치되어 있지 않음")
def test_potrace_runs_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    gray = np.full((60, 80), 255, np.uint8)
    gray[15:45, 20:60] = 0
    edges = smooth_edges(preprocess(gray), CFG)
    assert edges.shape == (60, 80)
    assert edges.min() < 64
