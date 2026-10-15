# 플로터 GUI 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 웹캠 촬영 → 해칭 → SVG/G-code 저장 → GRBL 아두이노로 시리얼 전송까지 하는 PyQt6 GUI를 만든다.

**Architecture:** `plotter/` 패키지에 역할별 모듈(설정, 해칭, 이미지 처리, 선 순서, G-code, SVG, GRBL 전송, 카메라)을 두고, 모두 Qt 없이 테스트할 수 있게 만든다. `plotter/gui/`는 상태 표(state), 이미지 변환(preview), 백그라운드 스레드(workers), 메인 창(main_window)으로 나눈다. `main.py`는 GUI를 실행하는 진입점만 남긴다.

**Tech Stack:** Python 3.12, uv, PyQt6, OpenCV, scikit-image, shapely 2, svgwrite, pyserial, pytest

**Spec:** `docs/superpowers/specs/2026-10-16-plotter-gui-design.md`

## Global Constraints

- Python `>=3.12`, 패키지 관리는 `uv` (`uv add`, `uv run`).
- 플랫폼: Windows 10. 카메라는 `cv2.CAP_DSHOW` 백엔드로 연다.
- 사용자에게 보이는 문자열(상태줄, 오류 메시지, 버튼)은 한국어. 코드 식별자는 영어.
- 선 목록 타입은 `plotter.lines.Polyline = list[tuple[float, float]]`, 모든 단계가 `list[Polyline]`을 주고받는다.
- 설정 기본값: 작업 영역 200 × 150 mm, 펜 `M3 S90`(내림) / `M5`(올림), 펜 대기 0.2초, 속도 3000 mm/분, baud 115200, potrace `C:/potrace.exe`, Inkscape `C:\Program Files\Inkscape\bin\inkscape.exe`, 해칭 간격 1 / 레벨 (20, 100, 180) / 각도 45°.
- 이미지 처리 파라미터는 기존 `main.py`와 동일: 블러 3×3, 적응형 이진화(19, 5), 모폴로지 열기 2×2 타원, potrace `--turdsize 2 --alphamax 1 --opttolerance 0.2 --unit 10`, 합성 `addWeighted(edges, 0.55, gray, 0.8, 1)`.
- 출력 파일: 프로젝트 루트의 `output.svg`, `output.gcode` (촬영할 때마다 덮어씀).
- `hatched` 패키지는 제거한다 (shapely 2.2와 호환되지 않음, 스펙 "설계 중 발견한 사항" 참고).

## Review Focus

1. **빈 화면 촬영** (렌즈를 가렸거나 하얀 벽): 선이 0개 → 예외 없이 "그릴 선이 없습니다" 표시, `전송` 비활성화. → Task 2 `test_white_image_has_no_lines`, Task 4 `test_generate_empty_lines`, Task 9 `test_empty_result_disables_send`.
2. **640×480이 아닌 카메라** (예: 1280×720): PBM 헤더가 실제 크기를 쓰고, G-code가 비율(16:9)을 유지한 채 작업 영역 안에 들어감. → Task 3 `test_to_pbm_uses_actual_size`, Task 4 `test_generate_keeps_aspect_ratio_for_wide_image`.
3. **GRBL이 아닌 장치나 엉뚱한 COM 포트 연결**: 몇 초 안에 "GRBL 응답이 없습니다"로 실패하고, 멈추지 않으며, 포트를 닫음. → Task 6 `test_connect_fails_without_banner`.
4. **일시정지한 상태에서 정지**: 멈추지 않고 정지 순서(`!`, 리셋, 펜 올림)를 끝냄. 일시정지 중에는 응답 시간 초과가 나지 않음. → Task 6 `test_stop_while_paused`, `test_pause_suspends_response_timeout`.
5. **설정 파일 오타나 잘못된 값** (`feed_rate = "fast"`, `feedrate = 3000`): 시작할 때 어떤 항목이 왜 잘못됐는지 대화상자로 알림 (트레이스백 대신). → Task 1 `test_unknown_key_is_rejected`, `test_wrong_type_is_rejected`, Task 9의 `main.py`.

---

## 파일 구조

```
config.toml                     # 사용자 설정 (기본값과 동일한 내용으로 제공)
main.py                         # GUI 진입점 (기존 스크립트 내용은 plotter/로 이동)
plotter/
  __init__.py
  config.py                     # Config 데이터클래스, load_config, ConfigError
  lines.py                      # Polyline 타입, order_lines (가까운 선부터 정렬)
  hatching.py                   # hatch_image (hatched 알고리즘 이식)
  processing.py                 # preprocess, to_pbm, smooth_edges, process, ProcessingError
  gcode.py                      # to_mm, generate, save_gcode
  svg_export.py                 # save_svg
  grbl_sender.py                # available_ports, connect, GrblSender, GrblError
  camera.py                     # list_cameras, open_camera, read_gray, CameraError
  gui/
    __init__.py
    state.py                    # AppState, Controls, controls_for
    preview.py                  # gray_to_qimage, render_lines
    workers.py                  # ProcessThread, SendThread
    main_window.py              # MainWindow
tests/
  test_config.py  test_hatching.py  test_processing.py  test_lines.py
  test_gcode.py   test_svg_export.py  test_grbl_sender.py  test_camera.py
  gui/
    conftest.py   test_state.py  test_preview.py  test_workers.py  test_main_window.py
```

테스트 파일 이름은 폴더가 달라도 모두 달라야 한다. `tests/`에는 `__init__.py`를 두지 않는다.

---

### Task 1: 프로젝트 설정과 Config

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `plotter/__init__.py`, `plotter/config.py`, `config.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `plotter.config.Config` (frozen dataclass): `work_width_mm: float`, `work_height_mm: float`, `pen_down: str`, `pen_up: str`, `pen_delay_s: float`, `feed_rate: float`, `baud: int`, `potrace_path: str`, `inkscape_path: str`, `hatch_pitch: float`, `hatch_levels: tuple[int, ...]`, `hatch_angle: float`
  - `plotter.config.load_config(path: Path) -> Config`. 파일이 없으면 `Config()`를 반환한다.
  - `plotter.config.ConfigError(Exception)`

- [ ] **Step 1: 의존성과 pytest 설정**

```powershell
uv add pyqt6 pyserial scikit-image shapely
uv add --dev pytest
```

`pyproject.toml` 끝에 추가:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`.gitignore` 끝에 추가:

```
# 실행 결과물
output.svg
output.gcode
```

`plotter/__init__.py`는 빈 파일로 만든다.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from plotter.config import Config, ConfigError, load_config

ROOT = Path(__file__).parent.parent


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_defaults_match_spec():
    cfg = Config()
    assert (cfg.work_width_mm, cfg.work_height_mm) == (200.0, 150.0)
    assert (cfg.pen_down, cfg.pen_up, cfg.pen_delay_s) == ("M3 S90", "M5", 0.2)
    assert (cfg.feed_rate, cfg.baud) == (3000.0, 115200)
    assert cfg.potrace_path == "C:/potrace.exe"
    assert cfg.inkscape_path == r"C:\Program Files\Inkscape\bin\inkscape.exe"
    assert (cfg.hatch_pitch, cfg.hatch_levels, cfg.hatch_angle) == (1.0, (20, 100, 180), 45.0)


def test_shipped_config_matches_defaults():
    assert load_config(ROOT / "config.toml") == Config()


def test_values_override_defaults(tmp_path):
    cfg = load_config(write(tmp_path, 'work_width_mm = 300\npen_down = "G1 Z0"\nhatch_levels = [50, 150]\n'))
    assert cfg.work_width_mm == 300.0
    assert isinstance(cfg.work_width_mm, float)
    assert cfg.pen_down == "G1 Z0"
    assert cfg.hatch_levels == (50, 150)
    assert cfg.pen_up == "M5"


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="feedrate"):
        load_config(write(tmp_path, "feedrate = 3000\n"))


def test_wrong_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="feed_rate"):
        load_config(write(tmp_path, 'feed_rate = "fast"\n'))


def test_bool_is_not_a_number(tmp_path):
    with pytest.raises(ConfigError, match="baud"):
        load_config(write(tmp_path, "baud = true\n"))


def test_non_positive_value_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="work_height_mm"):
        load_config(write(tmp_path, "work_height_mm = 0\n"))


def test_negative_pen_delay_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="pen_delay_s"):
        load_config(write(tmp_path, "pen_delay_s = -1\n"))


def test_levels_must_be_ascending_in_range(tmp_path):
    with pytest.raises(ConfigError, match="hatch_levels"):
        load_config(write(tmp_path, "hatch_levels = [180, 20]\n"))
    with pytest.raises(ConfigError, match="hatch_levels"):
        load_config(write(tmp_path, "hatch_levels = [0, 300]\n"))


def test_syntax_error_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="문법"):
        load_config(write(tmp_path, "work_width_mm = = 1\n"))
```

- [ ] **Step 3: 실패 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.config'`

- [ ] **Step 4: 구현**

`plotter/config.py`:

```python
"""config.toml을 읽어 Config로 만든다."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


class ConfigError(Exception):
    """설정 파일이 잘못되었을 때 발생한다. 메시지는 사용자에게 그대로 보여준다."""


@dataclass(frozen=True)
class Config:
    work_width_mm: float = 200.0
    work_height_mm: float = 150.0
    pen_down: str = "M3 S90"
    pen_up: str = "M5"
    pen_delay_s: float = 0.2
    feed_rate: float = 3000.0
    baud: int = 115200
    potrace_path: str = "C:/potrace.exe"
    inkscape_path: str = r"C:\Program Files\Inkscape\bin\inkscape.exe"
    hatch_pitch: float = 1.0
    hatch_levels: tuple[int, ...] = (20, 100, 180)
    hatch_angle: float = 45.0


_POSITIVE = ("work_width_mm", "work_height_mm", "feed_rate", "baud", "hatch_pitch")


def _coerce(name: str, value: object, default: object) -> object:
    if isinstance(default, tuple):
        ok = (
            isinstance(value, list)
            and value
            and all(isinstance(v, int) and not isinstance(v, bool) and 0 < v < 255 for v in value)
            and value == sorted(set(value))
        )
        if not ok:
            raise ConfigError(f"{name}: 1~254 사이 정수를 오름차순으로 나열해야 합니다 (값: {value!r})")
        return tuple(value)
    if isinstance(default, str):
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{name}: 비어 있지 않은 문자열이어야 합니다 (값: {value!r})")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name}: 정수여야 합니다 (값: {value!r})")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name}: 숫자여야 합니다 (값: {value!r})")
    return float(value)


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name} 문법 오류: {exc}") from exc

    defaults = Config()
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"알 수 없는 설정 항목: {', '.join(unknown)}")

    values = {name: _coerce(name, value, getattr(defaults, name)) for name, value in data.items()}
    cfg = Config(**values)

    for name in _POSITIVE:
        if getattr(cfg, name) <= 0:
            raise ConfigError(f"{name}: 0보다 커야 합니다 (값: {getattr(cfg, name)!r})")
    if cfg.pen_delay_s < 0:
        raise ConfigError(f"pen_delay_s: 0 이상이어야 합니다 (값: {cfg.pen_delay_s!r})")
    return cfg
```

`config.toml` (Windows 경로는 작은따옴표 문자열로 써야 역슬래시가 이스케이프되지 않는다):

```toml
# 플로터 설정. 항목을 지우면 기본값이 쓰입니다.

# 그릴 수 있는 영역 (mm). 그림은 비율을 유지한 채 이 안에 맞춰집니다.
work_width_mm = 200.0
work_height_mm = 150.0

# 펜 명령. 서보 GRBL 기본값. Z축이면 예: pen_down = "G1 Z0 F500", pen_up = "G0 Z5"
pen_down = "M3 S90"
pen_up = "M5"
# 펜을 올리고 내린 뒤 기다리는 시간 (초). 0이면 기다리지 않습니다.
pen_delay_s = 0.2

# 그리기 속도 (mm/분)
feed_rate = 3000.0
baud = 115200

potrace_path = 'C:/potrace.exe'
inkscape_path = 'C:\Program Files\Inkscape\bin\inkscape.exe'

# 해칭: 선 간격(픽셀), 밝기 단계(0~255 오름차순), 각도(도)
hatch_pitch = 1.0
hatch_levels = [20, 100, 180]
hatch_angle = 45.0
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml uv.lock .gitignore config.toml plotter/__init__.py plotter/config.py tests/test_config.py
git commit -m "feat: add config loading and project dependencies"
```

---

### Task 2: 해칭 모듈 (hatched 대체)

**Files:**
- Create: `plotter/lines.py` (이 Task에서는 타입만, `order_lines`는 Task 4)
- Create: `plotter/hatching.py`
- Modify: `pyproject.toml`, `uv.lock` (`hatched` 제거)
- Test: `tests/test_hatching.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `plotter.lines.Point = tuple[float, float]`, `plotter.lines.Polyline = list[Point]`
  - `plotter.hatching.hatch_image(img: np.ndarray, pitch: float, levels: tuple[int, ...], angle: float) -> list[Polyline]`. `img`는 2차원 uint8 흑백. 좌표는 픽셀 단위이고 `[3, w-6] × [3, h-6]` 안에 있다. 어두울수록 선이 촘촘하고, 가장 높은 레벨보다 밝은 영역에는 선이 없다.

**배경:** `hatched` 0.2.0의 `_build_hatch`는 shapely 2.2에서 첫 줄(`MultiLineString(np.empty(shape=(0, 2, 2)))`)에서 `ValueError`로 실패한다. 이 모듈은 같은 알고리즘(MIT 라이선스, https://github.com/abey79/hatched)을 옮기면서 두 가지를 고친다. 하나는 빈 MultiLineString을 만들지 않는 것이고, 다른 하나는 마스크가 없는 레벨(이미지 전체가 그 레벨보다 어두움)을 건너뛰지 않고 전부 해칭하는 것이다. 알고리즘은 다음과 같다. 이미지를 0으로 한 칸 둘러싸고 레벨별 등고선을 구해 "레벨보다 밝은 영역" 다각형(마스크)을 만든다. 레벨마다 간격이 다른 사선을 그린 뒤 마스크 영역을 빼면, 어두운 곳일수록 여러 레벨의 선이 겹쳐 촘촘해진다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_hatching.py`:

```python
import numpy as np

from plotter.hatching import hatch_image

LEVELS = (20, 100, 180)


def all_points(lines):
    return [p for line in lines for p in line]


def test_white_image_has_no_lines():
    assert hatch_image(np.full((120, 160), 255, np.uint8), 1.0, LEVELS, 45.0) == []


def test_black_image_is_fully_hatched():
    lines = hatch_image(np.zeros((120, 160), np.uint8), 1.0, LEVELS, 45.0)
    assert len(lines) > 50
    assert all(len(line) >= 2 for line in lines)


def test_lines_stay_inside_frame_for_non_square_image():
    h, w = 90, 200
    lines = hatch_image(np.zeros((h, w), np.uint8), 2.0, LEVELS, 45.0)
    for x, y in all_points(lines):
        assert 3 - 1e-6 <= x <= w - 6 + 1e-6
        assert 3 - 1e-6 <= y <= h - 6 + 1e-6


def test_only_dark_side_of_gradient_is_hatched():
    w = 255
    gradient = np.tile(np.arange(w, dtype=np.uint8), (100, 1))  # 왼쪽이 어둡다
    lines = hatch_image(gradient, 1.0, LEVELS, 45.0)
    assert lines
    # 밝기 180인 x=180 오른쪽(더 밝은 곳)에는 선이 없어야 한다
    # (등고선은 테두리를 1픽셀 덧댄 좌표라 몇 픽셀 여유를 둔다)
    assert max(x for x, _ in all_points(lines)) <= 185


def test_darker_means_more_ink():
    def ink(value):
        lines = hatch_image(np.full((100, 100), value, np.uint8), 1.0, LEVELS, 45.0)
        return sum(
            np.hypot(x2 - x1, y2 - y1)
            for line in lines
            for (x1, y1), (x2, y2) in zip(line, line[1:])
        )

    assert ink(10) > ink(60) > ink(140) > ink(250) == 0


def test_vertical_and_horizontal_angles_work():
    img = np.zeros((60, 80), np.uint8)
    for angle in (0.0, 90.0, 135.0):
        assert hatch_image(img, 2.0, LEVELS, angle)


def test_returns_plain_float_tuples():
    lines = hatch_image(np.zeros((40, 40), np.uint8), 2.0, LEVELS, 45.0)
    x, y = lines[0][0]
    assert type(x) is float and type(y) is float
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_hatching.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.hatching'`

- [ ] **Step 3: 구현**

`plotter/lines.py`:

```python
"""선 목록 타입. 모든 단계가 list[Polyline]을 주고받는다."""

from __future__ import annotations

Point = tuple[float, float]
Polyline = list[Point]
```

`plotter/hatching.py`:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_hatching.py -v`
Expected: 7 passed

- [ ] **Step 5: hatched 제거**

```powershell
uv remove hatched
uv run python -c "import cv2, importlib.util; print(cv2.__file__, importlib.util.find_spec('hatched'))"
```

Expected: `hatched`가 `None`. `opencv-python-headless`도 함께 빠졌는지 `uv pip list`로 확인한다. 기존 `main.py`는 아직 `hatched`를 import하지만, 이미 실행되지 않는 상태(스펙 참고)였고 Task 9에서 교체한다.

- [ ] **Step 6: Commit**

```powershell
git add plotter/lines.py plotter/hatching.py tests/test_hatching.py pyproject.toml uv.lock
git commit -m "feat: port hatching algorithm to shapely 2 and drop hatched"
```

---

### Task 3: 이미지 처리 (processing)

**Files:**
- Create: `plotter/processing.py`
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `hatch_image`, `Polyline` (Task 2)
- Produces:
  - `plotter.processing.ProcessingError(Exception)`: 메시지를 사용자에게 그대로 보여준다.
  - `preprocess(gray: np.ndarray) -> np.ndarray`: 입력과 같은 크기의 0/255 이진 이미지
  - `to_pbm(binary: np.ndarray) -> bytes`: potrace 입력용 P4 PBM (검은 픽셀 = 비트 1)
  - `smooth_edges(binary: np.ndarray, cfg: Config) -> np.ndarray`: potrace와 Inkscape를 거친 흑백 이미지 (입력과 같은 크기)
  - `process(gray: np.ndarray, cfg: Config) -> list[Polyline]`: 전체 파이프라인. 실패하면 `ProcessingError`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_processing.py`:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_processing.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.processing'`

- [ ] **Step 3: 구현**

`plotter/processing.py`:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_processing.py -v`
Expected: 6 passed, 그리고 potrace와 Inkscape가 설치되어 있으면 1 passed, 아니면 1 skipped

- [ ] **Step 5: Commit**

```powershell
git add plotter/processing.py tests/test_processing.py
git commit -m "feat: add image processing pipeline with actual-size PBM"
```

---

### Task 4: 선 정렬, G-code, SVG 출력

**Files:**
- Modify: `plotter/lines.py` (`order_lines` 추가)
- Create: `plotter/gcode.py`, `plotter/svg_export.py`
- Test: `tests/test_lines.py`, `tests/test_gcode.py`, `tests/test_svg_export.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `Polyline` (Task 2)
- Produces:
  - `plotter.lines.order_lines(lines: list[Polyline], start: Point = (0.0, 0.0)) -> list[Polyline]`: 현재 위치에서 가장 가까운 끝점의 선부터 이어 붙이고, 필요하면 선을 뒤집는다. 점이 2개 미만인 선은 버린다.
  - `plotter.gcode.to_mm(lines: list[Polyline], width: int, height: int, cfg: Config) -> list[Polyline]`
  - `plotter.gcode.generate(lines: list[Polyline], width: int, height: int, cfg: Config) -> list[str]`: 줄바꿈 없는 G-code 명령 목록
  - `plotter.gcode.save_gcode(commands: list[str], path: Path) -> None`
  - `plotter.svg_export.save_svg(lines: list[Polyline], width: int, height: int, path: Path) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_lines.py`:

```python
import time

import numpy as np

from plotter.lines import order_lines


def test_picks_nearest_line_first():
    far = [(100.0, 100.0), (110.0, 100.0)]
    near = [(1.0, 0.0), (5.0, 0.0)]
    assert order_lines([far, near]) == [near, far]


def test_reverses_line_when_end_is_closer():
    line = [(50.0, 0.0), (1.0, 0.0)]
    assert order_lines([line]) == [[(1.0, 0.0), (50.0, 0.0)]]


def test_continues_from_end_of_previous_line():
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(100.0, 0.0), (90.0, 0.0)]
    c = [(11.0, 0.0), (20.0, 0.0)]
    assert order_lines([a, b, c]) == [a, c, [(90.0, 0.0), (100.0, 0.0)]]


def test_drops_lines_with_fewer_than_two_points():
    assert order_lines([[(1.0, 1.0)], []]) == []


def test_empty_input():
    assert order_lines([]) == []


def test_keeps_every_line_and_is_fast_enough():
    rng = np.random.default_rng(1)
    lines = [[tuple(map(float, rng.random(2) * 200)), tuple(map(float, rng.random(2) * 200))] for _ in range(5000)]
    started = time.perf_counter()
    ordered = order_lines(lines)
    assert time.perf_counter() - started < 10
    assert len(ordered) == 5000
    assert sorted(map(sorted, ordered)) == sorted(map(sorted, lines))
```

`tests/test_gcode.py`:

```python
from dataclasses import replace

from plotter.config import Config
from plotter.gcode import generate, save_gcode, to_mm

CFG = Config()


def test_generate_empty_lines():
    assert generate([], 640, 480, CFG) == ["G21", "G90", "M5", "G4 P0.2", "G0 X0 Y0"]


def test_generate_single_line_full_diagonal():
    # 이미지 왼쪽 아래 (0, 480) → 오른쪽 위 (640, 0) = 플로터 (0, 0) → (200, 150)
    commands = generate([[(0.0, 480.0), (640.0, 0.0)]], 640, 480, CFG)
    assert commands == [
        "G21", "G90", "M5", "G4 P0.2",
        "G0 X0.00 Y0.00",
        "M3 S90", "G4 P0.2",
        "G1 X200.00 Y150.00 F3000",
        "M5", "G4 P0.2",
        "G0 X0 Y0",
    ]


def test_feed_rate_only_on_first_move_of_each_stroke():
    commands = generate([[(0.0, 480.0), (320.0, 480.0), (640.0, 480.0)]], 640, 480, CFG)
    g1 = [c for c in commands if c.startswith("G1")]
    assert g1 == ["G1 X100.00 Y0.00 F3000", "G1 X200.00 Y0.00"]


def test_generate_keeps_aspect_ratio_for_wide_image():
    # 1280x720(16:9)는 가로에 맞춰져 높이가 112.5mm가 된다
    mm = to_mm([[(0.0, 0.0), (1280.0, 720.0)]], 1280, 720, CFG)
    assert mm == [[(0.0, 112.5), (200.0, 0.0)]]


def test_coordinates_are_clamped_to_work_area():
    mm = to_mm([[(-5.0, 500.0), (700.0, -10.0)]], 640, 480, CFG)
    assert mm == [[(0.0, 0.0), (200.0, 150.0)]]


def test_custom_pen_commands_and_no_dwell():
    cfg = replace(CFG, pen_down="G1 Z0 F500", pen_up="G0 Z5", pen_delay_s=0.0)
    commands = generate([[(0.0, 480.0), (640.0, 480.0)]], 640, 480, cfg)
    assert "G1 Z0 F500" in commands
    assert commands.count("G0 Z5") == 2
    assert not any(c.startswith("G4") for c in commands)


def test_strokes_are_ordered_nearest_first():
    far = [(640.0, 0.0), (600.0, 0.0)]       # 플로터 (200,150) 근처
    near = [(0.0, 480.0), (40.0, 480.0)]     # 플로터 원점
    commands = generate([far, near], 640, 480, CFG)
    rapids = [c for c in commands if c.startswith("G0 X") and c != "G0 X0 Y0"]
    assert rapids == ["G0 X0.00 Y0.00", "G0 X187.50 Y150.00"]


def test_save_gcode_writes_one_command_per_line(tmp_path):
    path = tmp_path / "out.gcode"
    save_gcode(["G21", "G90"], path)
    assert path.read_text(encoding="utf-8") == "G21\nG90\n"
```

`tests/test_svg_export.py`:

```python
import xml.etree.ElementTree as ET

from plotter.svg_export import save_svg

SVG = "{http://www.w3.org/2000/svg}"


def test_save_svg_writes_size_and_paths(tmp_path):
    path = tmp_path / "out.svg"
    save_svg([[(0.0, 0.0), (10.0, 5.0)], [(1.0, 1.0), (2.0, 2.0), (3.0, 1.0)]], 1280, 720, path)
    root = ET.parse(path).getroot()
    assert root.get("width") == "1280"
    assert root.get("height") == "720"
    d = root.find(f"{SVG}path").get("d")
    assert d == "M0.00,0.00 L10.00,5.00 M1.00,1.00 L2.00,2.00 L3.00,1.00"


def test_save_svg_with_no_lines_is_valid_and_empty(tmp_path):
    path = tmp_path / "out.svg"
    save_svg([], 640, 480, path)
    root = ET.parse(path).getroot()
    assert root.find(f"{SVG}path") is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_lines.py tests/test_gcode.py tests/test_svg_export.py -v`
Expected: FAIL, `ImportError: cannot import name 'order_lines'` 및 `ModuleNotFoundError` (gcode, svg_export)

- [ ] **Step 3: 구현**

`plotter/lines.py` 전체를 다음으로 바꾼다:

```python
"""선 목록 타입과 그리는 순서 정렬."""

from __future__ import annotations

import numpy as np

Point = tuple[float, float]
Polyline = list[Point]


def order_lines(lines: list[Polyline], start: Point = (0.0, 0.0)) -> list[Polyline]:
    """펜을 든 채 이동하는 거리가 줄도록, 가장 가까운 끝점의 선부터 이어 붙인다."""
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return []
    starts = np.array([line[0] for line in lines], dtype=float)
    ends = np.array([line[-1] for line in lines], dtype=float)
    remaining = np.ones(len(lines), dtype=bool)
    pos = np.array(start, dtype=float)
    ordered: list[Polyline] = []
    for _ in range(len(lines)):
        d_start = np.where(remaining, np.hypot(*(starts - pos).T), np.inf)
        d_end = np.where(remaining, np.hypot(*(ends - pos).T), np.inf)
        i_start = int(np.argmin(d_start))
        i_end = int(np.argmin(d_end))
        if d_start[i_start] <= d_end[i_end]:
            index, line = i_start, list(lines[i_start])
        else:
            index, line = i_end, list(reversed(lines[i_end]))
        remaining[index] = False
        ordered.append(line)
        pos = np.array(line[-1], dtype=float)
    return ordered
```

`plotter/gcode.py`:

```python
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
```

`plotter/svg_export.py`:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_lines.py tests/test_gcode.py tests/test_svg_export.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```powershell
git add plotter/lines.py plotter/gcode.py plotter/svg_export.py tests/test_lines.py tests/test_gcode.py tests/test_svg_export.py
git commit -m "feat: add stroke ordering, G-code generation and SVG export"
```

---

### Task 5: 카메라

**Files:**
- Create: `plotter/camera.py`
- Test: `tests/test_camera.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `plotter.camera.CameraError(Exception)`
  - `list_cameras(max_index: int = 6, capture_factory=cv2.VideoCapture) -> list[int]`: 열리는 카메라 번호 목록
  - `open_camera(index: int, capture_factory=cv2.VideoCapture) -> cv2.VideoCapture`: 실패하면 `CameraError`
  - `read_gray(capture) -> np.ndarray | None`: 프레임을 읽어 흑백으로. 실패하면 `None`

`capture_factory`는 `(index: int, api: int)`를 받아 `isOpened()`, `read()`, `release()`가 있는 객체를 돌려주는 callable이다. 테스트에서 가짜 객체를 넣기 위해 둔다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_camera.py`:

```python
import cv2
import numpy as np
import pytest

from plotter.camera import CameraError, list_cameras, open_camera, read_gray


class FakeCapture:
    released: list[int] = []

    def __init__(self, index, api, available=(0, 2), frame=None):
        self.index, self.api = index, api
        self._open = index in available
        self._frame = frame

    def isOpened(self):
        return self._open

    def read(self):
        return (self._frame is not None, self._frame)

    def release(self):
        FakeCapture.released.append(self.index)


def test_list_cameras_returns_openable_indices_and_releases_all():
    FakeCapture.released = []
    assert list_cameras(4, FakeCapture) == [0, 2]
    assert sorted(FakeCapture.released) == [0, 1, 2, 3]


def test_cameras_are_opened_with_directshow():
    seen = []

    def factory(index, api):
        seen.append(api)
        return FakeCapture(index, api)

    list_cameras(2, factory)
    open_camera(0, factory)
    assert set(seen) == {cv2.CAP_DSHOW}


def test_open_camera_fails_for_missing_device():
    with pytest.raises(CameraError, match="카메라 1"):
        open_camera(1, FakeCapture)


def test_read_gray_converts_bgr_frame():
    frame = np.zeros((4, 6, 3), np.uint8)
    frame[..., 2] = 255  # 빨강
    gray = read_gray(FakeCapture(0, 0, frame=frame))
    assert gray.shape == (4, 6)
    assert gray.dtype == np.uint8
    assert int(gray[0, 0]) == 76  # 0.299 * 255


def test_read_gray_returns_none_on_failure():
    assert read_gray(FakeCapture(0, 0, frame=None)) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_camera.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.camera'`

- [ ] **Step 3: 구현**

`plotter/camera.py`:

```python
"""웹캠 탐색, 열기, 흑백 프레임 읽기."""

from __future__ import annotations

import cv2
import numpy as np


class CameraError(Exception):
    """카메라를 열 수 없을 때 발생한다."""


def list_cameras(max_index: int = 6, capture_factory=cv2.VideoCapture) -> list[int]:
    found = []
    for index in range(max_index):
        capture = capture_factory(index, cv2.CAP_DSHOW)
        try:
            if capture.isOpened():
                found.append(index)
        finally:
            capture.release()
    return found


def open_camera(index: int, capture_factory=cv2.VideoCapture):
    capture = capture_factory(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        raise CameraError(f"카메라 {index}을(를) 열 수 없습니다")
    return capture


def read_gray(capture) -> np.ndarray | None:
    ok, frame = capture.read()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_camera.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```powershell
git add plotter/camera.py tests/test_camera.py
git commit -m "feat: add camera discovery and grayscale capture"
```

---

### Task 6: GRBL 전송

**Files:**
- Create: `plotter/grbl_sender.py`
- Test: `tests/test_grbl_sender.py`

**Interfaces:**
- Consumes: 없음 (펜 올림 명령 문자열은 호출하는 쪽이 `Config.pen_up`을 넘긴다)
- Produces:
  - `plotter.grbl_sender.GrblError(Exception)`: 메시지를 사용자에게 그대로 보여준다.
  - `available_ports() -> list[str]`: 예 `["COM3", "COM5"]`
  - `connect(port_name: str, baud: int, timeout_s: float = 3.0, serial_factory=serial.Serial)`: GRBL 시작 메시지를 확인한 열린 포트. 실패하면 포트를 닫고 `GrblError`. `serial_factory(port_name, baud, timeout=0.2)`로 호출한다.
  - `GrblSender(port, pen_up: str, response_timeout_s: float = 30.0, hold_settle_s: float = 0.5)`
    - `stream(commands: list[str], on_progress: Callable[[int, int], None] = ...) -> bool`: 끝까지 보내면 `True`, 정지 요청으로 멈추면 `False`. 오류가 나면 펜을 올린 뒤 `GrblError`를 던진다. 다른 스레드에서 호출해도 된다.
    - `pause()`, `resume()`, `request_stop()`: GUI 스레드에서 호출한다. 시리얼 쓰기는 내부 잠금으로 보호한다.

**GRBL 동작 요약** (구현할 사람을 위한 배경 설명):
- 명령 한 줄을 받으면 `ok`(성공)나 `error:N`(실패)으로 응답한다. 알람 상태가 되면 `ALARM:N`을 보낸다. `[MSG:...]` 같은 다른 메시지도 섞여 올 수 있다.
- `ok`는 명령을 버퍼에 넣었다는 뜻이고, 실제 움직임은 나중에 끝난다. `G4 P0`(대기)에 대한 `ok`는 버퍼가 다 비워진 뒤에 오므로, 완료 신호로 쓸 수 있다.
- 실시간 명령은 줄바꿈 없이 1바이트로 보낸다: `!` 멈춤, `~` 재개, `\x18`(Ctrl-X) 소프트 리셋. 리셋하면 `Grbl 1.1h ['$' for help]` 같은 시작 메시지가 다시 온다.
- 아두이노는 포트를 열면 재부팅하면서 시작 메시지를 보낸다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_grbl_sender.py`:

```python
import threading
import time
from collections import deque

import pytest
import serial

from plotter.grbl_sender import GrblError, GrblSender, connect

BANNER = b"Grbl 1.1h ['$' for help]\r\n"


class FakeGrbl:
    """GRBL처럼 줄마다 ok를 돌려주는 가짜 시리얼 포트."""

    def __init__(self, *, banner=False, error_on=None, silent=False, answers_reset=True):
        self.writes: list[bytes] = []
        self._replies = deque([BANNER] if banner else [])
        self.error_on = error_on
        self.silent = silent
        self.answers_reset = answers_reset
        self.lines_received = 0
        self.on_line = None
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"\x18":
            if self.answers_reset:
                self._replies.append(BANNER)
            return 1
        if data in (b"!", b"~"):
            return 1
        self.lines_received += 1
        if self.on_line:
            self.on_line(self.lines_received)
        if not self.silent:
            self._replies.append(b"error:20\r\n" if self.error_on == self.lines_received else b"ok\r\n")
        return len(data)

    def readline(self) -> bytes:
        if self._replies:
            return self._replies.popleft()
        time.sleep(0.001)
        return b""

    def close(self):
        self.closed = True


def make_sender(port, **kwargs):
    kwargs.setdefault("hold_settle_s", 0)
    return GrblSender(port, "M5", **kwargs)


def test_stream_sends_all_lines_then_syncs_and_reports_progress():
    port = FakeGrbl()
    progress = []
    assert make_sender(port).stream(["G21", "G90", "G1 X1 Y1"], lambda d, t: progress.append((d, t))) is True
    assert port.writes == [b"G21\n", b"G90\n", b"G1 X1 Y1\n", b"G4 P0\n"]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_stream_ignores_status_messages():
    port = FakeGrbl()
    port._replies.append(b"[MSG:Caution: Unlocked]\r\n")
    assert make_sender(port).stream(["G21"]) is True


def test_grbl_error_raises_with_line_number_and_lifts_pen():
    port = FakeGrbl(error_on=2)
    with pytest.raises(GrblError, match="2번째 줄 'G90'.*error:20"):
        make_sender(port).stream(["G21", "G90", "G1 X1"])
    assert b"G1 X1\n" not in port.writes
    tail = port.writes[port.writes.index(b"G90\n") + 1:]
    assert tail == [b"!", b"\x18", b"M5\n"]


def test_stop_request_aborts_and_lifts_pen():
    port = FakeGrbl()
    sender = make_sender(port)
    port.on_line = lambda n: sender.request_stop() if n == 2 else None
    assert sender.stream(["G21", "G90", "G1 X1"]) is False
    assert port.writes == [b"G21\n", b"G90\n", b"!", b"\x18", b"M5\n"]


def test_pause_and_resume_send_realtime_commands():
    port = FakeGrbl()
    sender = make_sender(port)
    sender.pause()
    sender.resume()
    assert port.writes == [b"!", b"~"]


def test_stop_while_paused():
    port = FakeGrbl()
    sender = make_sender(port)

    def on_line(n):
        if n == 1:
            sender.pause()
            sender.request_stop()

    port.on_line = on_line
    assert sender.stream(["G21", "G90"]) is False
    assert port.writes[-3:] == [b"!", b"\x18", b"M5\n"]
    assert b"G90\n" not in port.writes


def test_silent_device_times_out():
    port = FakeGrbl(silent=True)
    with pytest.raises(GrblError, match="1번째 줄 'G21'.*응답이 없습니다"):
        make_sender(port, response_timeout_s=0.1).stream(["G21"])


def test_pause_suspends_response_timeout():
    port = FakeGrbl(silent=True)
    sender = make_sender(port, response_timeout_s=0.1)
    port.on_line = lambda n: sender.pause() if n == 1 else None
    result = {}
    thread = threading.Thread(target=lambda: result.update(value=sender.stream(["G21"])))
    thread.start()
    time.sleep(0.4)
    assert thread.is_alive()  # 일시정지 중이라 시간 초과가 나지 않는다
    sender.request_stop()
    thread.join(timeout=5)
    assert result == {"value": False}


def test_disconnect_raises_grbl_error():
    class Unplugged(FakeGrbl):
        def write(self, data):
            raise serial.SerialException("device disconnected")

    with pytest.raises(GrblError, match="끊겼습니다"):
        make_sender(Unplugged()).stream(["G21"])


def test_connect_accepts_banner():
    port = FakeGrbl(banner=True)
    assert connect("COM9", 115200, timeout_s=0.5, serial_factory=lambda name, baud, timeout: port) is port
    assert port.writes == []


def test_connect_resets_when_banner_missing():
    port = FakeGrbl(banner=False)
    assert connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, timeout: port) is port
    assert port.writes == [b"\x18"]


def test_connect_fails_without_banner():
    port = FakeGrbl(banner=False, answers_reset=False)
    started = time.monotonic()
    with pytest.raises(GrblError, match="COM9.*GRBL 응답이 없습니다"):
        connect("COM9", 115200, timeout_s=0.1, serial_factory=lambda name, baud, timeout: port)
    assert time.monotonic() - started < 2
    assert port.closed


def test_connect_reports_unopenable_port():
    def factory(name, baud, timeout):
        raise serial.SerialException("access denied")

    with pytest.raises(GrblError, match="COM9.*열 수 없습니다"):
        connect("COM9", 115200, serial_factory=factory)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_grbl_sender.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.grbl_sender'`

- [ ] **Step 3: 구현**

`plotter/grbl_sender.py`:

```python
"""GRBL로 G-code를 한 줄씩 보내고 ok를 기다린다 (send-response 방식)."""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Callable

import serial
from serial.tools import list_ports

_SYNC = "G4 P0"  # GRBL은 버퍼가 다 비워진 뒤에 이 명령에 ok를 보낸다
_FEED_HOLD = b"!"
_CYCLE_START = b"~"
_SOFT_RESET = b"\x18"


class GrblError(Exception):
    """GRBL 통신 실패. 메시지는 사용자에게 그대로 보여준다."""


def available_ports() -> list[str]:
    return sorted(port.device for port in list_ports.comports())


def _read_text(port) -> str:
    try:
        return port.readline().decode(errors="replace").strip()
    except serial.SerialException as exc:
        raise GrblError(f"시리얼 연결이 끊겼습니다: {exc}") from exc


def _wait_for_banner(port, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _read_text(port).startswith("Grbl"):
            return True
    return False


def connect(port_name: str, baud: int, timeout_s: float = 3.0, serial_factory=serial.Serial):
    try:
        port = serial_factory(port_name, baud, timeout=0.2)
    except serial.SerialException as exc:
        raise GrblError(f"{port_name}을(를) 열 수 없습니다: {exc}") from exc
    try:
        if _wait_for_banner(port, timeout_s):
            return port
        port.write(_SOFT_RESET)
        if _wait_for_banner(port, timeout_s):
            return port
    except (GrblError, serial.SerialException):
        pass
    port.close()
    raise GrblError(f"{port_name}에서 GRBL 응답이 없습니다. 포트와 펌웨어를 확인하세요")


class GrblSender:
    def __init__(self, port, pen_up: str, response_timeout_s: float = 30.0, hold_settle_s: float = 0.5):
        self._port = port
        self._pen_up = pen_up
        self._response_timeout_s = response_timeout_s
        self._hold_settle_s = hold_settle_s
        # RLock: 같은 스레드가 쓰는 도중 다시 pause()를 불러도 멈추지 않게 한다
        self._write_lock = threading.RLock()
        self._paused = threading.Event()
        self._stop = threading.Event()

    def pause(self) -> None:
        self._paused.set()
        self._write(_FEED_HOLD)

    def resume(self) -> None:
        self._paused.clear()
        self._write(_CYCLE_START)

    def request_stop(self) -> None:
        self._stop.set()

    def stream(self, commands: list[str], on_progress: Callable[[int, int], None] = lambda done, total: None) -> bool:
        self._stop.clear()
        self._paused.clear()
        total = len(commands)
        try:
            for index, command in enumerate(commands, start=1):
                if not self._send_and_wait(index, command):
                    self._abort()
                    return False
                on_progress(index, total)
            if not self._send_and_wait(total + 1, _SYNC):
                self._abort()
                return False
            return True
        except GrblError:
            with contextlib.suppress(GrblError):
                self._abort()
            raise

    def _write(self, data: bytes) -> None:
        try:
            with self._write_lock:
                self._port.write(data)
        except serial.SerialException as exc:
            raise GrblError(f"시리얼 연결이 끊겼습니다: {exc}") from exc

    def _send_and_wait(self, index: int, command: str) -> bool:
        """ok를 받으면 True, 정지 요청이면 False. error/ALARM/응답 없음은 GrblError."""
        if self._stop.is_set():
            return False
        self._write(command.encode("ascii") + b"\n")
        deadline = time.monotonic() + self._response_timeout_s
        while True:
            if self._stop.is_set():
                return False
            reply = _read_text(self._port)
            if reply == "ok":
                return True
            if reply.startswith(("error", "ALARM")):
                raise GrblError(f"{index}번째 줄 '{command}'에서 GRBL 오류: {reply}")
            if reply:
                continue  # [MSG:...] 같은 상태 메시지는 무시
            if self._paused.is_set():
                deadline = time.monotonic() + self._response_timeout_s
            elif time.monotonic() > deadline:
                raise GrblError(f"{index}번째 줄 '{command}'에 GRBL 응답이 없습니다")

    def _abort(self) -> None:
        """멈춤 → 리셋(버퍼 비움) → 펜 올림. 멈춘 뒤 리셋하면 위치를 잃지 않는다."""
        self._write(_FEED_HOLD)
        time.sleep(self._hold_settle_s)
        self._write(_SOFT_RESET)
        _wait_for_banner(self._port, 2.0)
        self._paused.clear()
        self._write(self._pen_up.encode("ascii") + b"\n")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if _read_text(self._port) == "ok":
                break
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_grbl_sender.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```powershell
git add plotter/grbl_sender.py tests/test_grbl_sender.py
git commit -m "feat: add GRBL streaming with pause, resume and safe stop"
```

---

### Task 7: GUI 상태 표와 이미지 변환

**Files:**
- Create: `plotter/gui/__init__.py` (빈 파일), `plotter/gui/state.py`, `plotter/gui/preview.py`
- Create: `tests/gui/conftest.py`
- Test: `tests/gui/test_state.py`, `tests/gui/test_preview.py`

**Interfaces:**
- Consumes: `Polyline` (Task 2)
- Produces:
  - `plotter.gui.state.AppState` (Enum): `LIVE`, `PROCESSING`, `REVIEW`, `SENDING`, `PAUSED`
  - `plotter.gui.state.Controls` (frozen dataclass, 모두 `bool`): `select_camera`, `select_port`, `capture`, `retake`, `send`, `pause`, `resume`, `stop`
  - `plotter.gui.state.controls_for(state: AppState, *, camera_ready: bool, port_connected: bool, has_lines: bool) -> Controls`
  - `plotter.gui.preview.gray_to_qimage(gray: np.ndarray) -> QImage`
  - `plotter.gui.preview.render_lines(lines: list[Polyline], width: int, height: int) -> QImage`
  - pytest fixture `qapp` (`tests/gui/conftest.py`): offscreen `QApplication`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/conftest.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
```

`tests/gui/test_state.py`:

```python
import pytest

from plotter.gui.state import AppState, Controls, controls_for


def controls(state, camera_ready=True, port_connected=True, has_lines=True):
    return controls_for(state, camera_ready=camera_ready, port_connected=port_connected, has_lines=has_lines)


def test_live_allows_capture_and_device_selection():
    assert controls(AppState.LIVE) == Controls(
        select_camera=True, select_port=True, capture=True, retake=False,
        send=False, pause=False, resume=False, stop=False,
    )


def test_live_without_camera_cannot_capture():
    assert controls(AppState.LIVE, camera_ready=False).capture is False


def test_processing_disables_everything_but_port():
    c = controls(AppState.PROCESSING)
    assert (c.select_camera, c.capture, c.retake, c.send, c.pause, c.resume, c.stop) == (False,) * 7
    assert c.select_port is True


def test_review_allows_send_only_when_connected_with_lines():
    assert controls(AppState.REVIEW).send is True
    assert controls(AppState.REVIEW, port_connected=False).send is False
    assert controls(AppState.REVIEW, has_lines=False).send is False
    assert controls(AppState.REVIEW).retake is True
    assert controls(AppState.REVIEW).select_camera is False


@pytest.mark.parametrize("state", [AppState.SENDING, AppState.PAUSED])
def test_drawing_locks_port_and_allows_stop(state):
    c = controls(state)
    assert c.stop is True
    assert c.select_port is False
    assert (c.capture, c.retake, c.send) == (False, False, False)


def test_pause_and_resume_are_exclusive():
    assert (controls(AppState.SENDING).pause, controls(AppState.SENDING).resume) == (True, False)
    assert (controls(AppState.PAUSED).pause, controls(AppState.PAUSED).resume) == (False, True)
```

`tests/gui/test_preview.py`:

```python
import numpy as np

from plotter.gui.preview import gray_to_qimage, render_lines


def test_gray_to_qimage_keeps_pixel_values(qapp):
    gray = np.array([[0, 50, 100, 150], [200, 250, 10, 20], [30, 40, 60, 70]], np.uint8)
    image = gray_to_qimage(gray)
    assert (image.width(), image.height()) == (4, 3)
    for y in range(3):
        for x in range(4):
            assert image.pixelColor(x, y).red() == gray[y, x]


def test_gray_to_qimage_accepts_non_contiguous_array(qapp):
    gray = np.arange(64, dtype=np.uint8).reshape(8, 8)[:, ::2]
    image = gray_to_qimage(gray)
    assert image.pixelColor(1, 0).red() == gray[0, 1]


def test_render_lines_draws_black_on_white(qapp):
    # y=50.5는 50번째 픽셀 줄의 한가운데라 안티앨리어싱으로 흐려지지 않는다
    image = render_lines([[(0.0, 50.5), (99.0, 50.5)]], 100, 100)
    assert (image.width(), image.height()) == (100, 100)
    assert image.pixelColor(50, 50).lightness() < 128
    assert image.pixelColor(50, 10).lightness() == 255


def test_render_lines_with_no_lines_is_blank(qapp):
    image = render_lines([], 10, 10)
    assert all(image.pixelColor(x, y).lightness() == 255 for x in range(10) for y in range(10))
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/gui/test_state.py tests/gui/test_preview.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.gui'`

- [ ] **Step 3: 구현**

`plotter/gui/__init__.py`: 빈 파일.

`plotter/gui/state.py`:

```python
"""화면 상태별로 어떤 버튼을 누를 수 있는지 정한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class AppState(Enum):
    LIVE = auto()        # 카메라 미리보기, 촬영 대기
    PROCESSING = auto()  # 이미지 처리 중
    REVIEW = auto()      # 결과 확인, 전송 대기
    SENDING = auto()     # 그리는 중
    PAUSED = auto()      # 그리기 일시정지


@dataclass(frozen=True)
class Controls:
    select_camera: bool
    select_port: bool
    capture: bool
    retake: bool
    send: bool
    pause: bool
    resume: bool
    stop: bool


def controls_for(state: AppState, *, camera_ready: bool, port_connected: bool, has_lines: bool) -> Controls:
    drawing = state in (AppState.SENDING, AppState.PAUSED)
    return Controls(
        select_camera=state is AppState.LIVE,
        select_port=not drawing,
        capture=state is AppState.LIVE and camera_ready,
        retake=state is AppState.REVIEW,
        send=state is AppState.REVIEW and port_connected and has_lines,
        pause=state is AppState.SENDING,
        resume=state is AppState.PAUSED,
        stop=drawing,
    )
```

`plotter/gui/preview.py`:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/gui/test_state.py tests/gui/test_preview.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```powershell
git add plotter/gui/__init__.py plotter/gui/state.py plotter/gui/preview.py tests/gui/conftest.py tests/gui/test_state.py tests/gui/test_preview.py
git commit -m "feat: add GUI state table and image conversion helpers"
```

---

### Task 8: 백그라운드 스레드

**Files:**
- Create: `plotter/gui/workers.py`
- Test: `tests/gui/test_workers.py`

**Interfaces:**
- Consumes: `process`, `ProcessingError` (Task 3), `GrblSender`, `GrblError` (Task 6), `Config` (Task 1)
- Produces:
  - `ProcessThread(gray: np.ndarray, cfg: Config, parent=None)` (QThread). 시그널은 `succeeded(object)`(값은 `list[Polyline]`), `failed(str)`.
  - `SendThread(sender: GrblSender, commands: list[str], parent=None)` (QThread). 시그널은 `progress(int, int)`, `completed(bool)`(True면 끝까지 그림, False면 정지됨), `failed(str)`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/test_workers.py`:

```python
from dataclasses import replace

import numpy as np

from plotter.config import Config
from plotter.grbl_sender import GrblError
from plotter.gui.workers import ProcessThread, SendThread


def run_thread(qapp, thread):
    thread.start()
    assert thread.wait(5000)
    qapp.processEvents()


class FakeSender:
    def __init__(self, result=True, error=None):
        self.result, self.error = result, error

    def stream(self, commands, on_progress):
        for i in range(1, len(commands) + 1):
            on_progress(i, len(commands))
        if self.error:
            raise self.error
        return self.result


def test_process_thread_reports_processing_error(qapp):
    cfg = replace(Config(), potrace_path="C:/nope/potrace.exe")
    thread = ProcessThread(np.full((20, 20), 255, np.uint8), cfg)
    failures, results = [], []
    thread.failed.connect(failures.append)
    thread.succeeded.connect(results.append)
    run_thread(qapp, thread)
    assert results == []
    assert len(failures) == 1 and "potrace" in failures[0]


def test_send_thread_reports_progress_and_completion(qapp):
    thread = SendThread(FakeSender(result=True), ["G21", "G90"])
    progress, done = [], []
    thread.progress.connect(lambda d, t: progress.append((d, t)))
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert progress == [(1, 2), (2, 2)]
    assert done == [True]


def test_send_thread_reports_stop(qapp):
    thread = SendThread(FakeSender(result=False), ["G21"])
    done = []
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert done == [False]


def test_send_thread_reports_grbl_error(qapp):
    thread = SendThread(FakeSender(error=GrblError("1번째 줄 'G21'에서 GRBL 오류: error:20")), ["G21"])
    failures, done = [], []
    thread.failed.connect(failures.append)
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert failures == ["1번째 줄 'G21'에서 GRBL 오류: error:20"]
    assert done == []


def test_send_thread_wraps_unexpected_error(qapp):
    thread = SendThread(FakeSender(error=RuntimeError("boom")), ["G21"])
    failures = []
    thread.failed.connect(failures.append)
    run_thread(qapp, thread)
    assert failures and "boom" in failures[0]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/gui/test_workers.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.gui.workers'`

- [ ] **Step 3: 구현**

`plotter/gui/workers.py`:

```python
"""이미지 처리와 GRBL 전송을 GUI 스레드 밖에서 실행한다."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from plotter.config import Config
from plotter.grbl_sender import GrblError, GrblSender
from plotter.processing import ProcessingError, process


class ProcessThread(QThread):
    succeeded = pyqtSignal(object)  # list[Polyline]
    failed = pyqtSignal(str)

    def __init__(self, gray: np.ndarray, cfg: Config, parent=None):
        super().__init__(parent)
        self._gray = gray
        self._cfg = cfg

    def run(self) -> None:
        try:
            lines = process(self._gray, self._cfg)
        except ProcessingError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # 스레드 밖으로 예외가 나가면 조용히 사라지므로 모두 알린다
            self.failed.emit(f"이미지 처리 중 예상치 못한 오류: {exc}")
            return
        self.succeeded.emit(lines)


class SendThread(QThread):
    progress = pyqtSignal(int, int)
    completed = pyqtSignal(bool)  # True: 끝까지 그림, False: 정지됨
    failed = pyqtSignal(str)

    def __init__(self, sender: GrblSender, commands: list[str], parent=None):
        super().__init__(parent)
        self._sender = sender
        self._commands = commands

    def run(self) -> None:
        try:
            finished = self._sender.stream(self._commands, self.progress.emit)
        except GrblError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"전송 중 예상치 못한 오류: {exc}")
            return
        self.completed.emit(finished)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/gui/test_workers.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```powershell
git add plotter/gui/workers.py tests/gui/test_workers.py
git commit -m "feat: add background threads for processing and sending"
```

---

### Task 9: 메인 창, 진입점, 문서

**Files:**
- Create: `plotter/gui/main_window.py`
- Modify: `main.py` (전체 교체)
- Modify: `CLAUDE.md` (전체 교체)
- Test: `tests/gui/test_main_window.py`

**Interfaces:**
- Consumes: Task 1~8의 모든 공개 함수와 클래스
- Produces: `plotter.gui.main_window.MainWindow(cfg: Config, output_dir: Path, settings: QSettings | None = None)`. `settings`가 `None`이면 `QSettings("TeslaPlotter", "PlotterPathGenerator")`를 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/test_main_window.py`:

```python
import pytest
from PyQt6.QtCore import QSettings

from plotter import camera, grbl_sender
from plotter.config import Config
from plotter.gui.main_window import MainWindow
from plotter.gui.state import AppState


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "list_cameras", lambda *a, **k: [])
    monkeypatch.setattr(grbl_sender, "available_ports", lambda: ["COM7"])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w = MainWindow(Config(), tmp_path, settings)
    yield w
    w.close()


def test_starts_live_without_camera(window):
    assert window._state is AppState.LIVE
    assert not window._capture_button.isEnabled()
    assert "카메라를 찾을 수 없습니다" in window._status.text()
    assert window._port_combo.currentText() == "COM7"


def test_processed_result_is_saved_and_reviewed(window, tmp_path):
    window._image_size = (640, 480)
    window._on_processed([[(10.0, 10.0), (100.0, 100.0)]])
    assert window._state is AppState.REVIEW
    assert (tmp_path / "output.svg").exists()
    gcode = (tmp_path / "output.gcode").read_text(encoding="utf-8")
    assert gcode.startswith("G21\nG90\n")
    assert window._retake_button.isEnabled()
    assert not window._send_button.isEnabled()  # 포트가 연결되지 않음


def test_empty_result_disables_send(window):
    window._image_size = (640, 480)
    window._serial = object()  # 연결된 것처럼
    window._on_processed([])
    assert window._state is AppState.REVIEW
    assert not window._send_button.isEnabled()
    assert "그릴 선이 없습니다" in window._status.text()
    window._serial = None


def test_processing_failure_returns_to_live(window):
    window._state = AppState.PROCESSING
    window._on_process_failed("potrace을(를) 찾을 수 없습니다: C:/potrace.exe")
    assert window._state is AppState.LIVE
    assert "potrace" in window._status.text()


def test_connect_failure_is_shown(window, monkeypatch):
    def fail(name, baud):
        raise grbl_sender.GrblError(f"{name}에서 GRBL 응답이 없습니다. 포트와 펌웨어를 확인하세요")

    monkeypatch.setattr(grbl_sender, "connect", fail)
    window._toggle_connection()
    assert window._serial is None
    assert "GRBL 응답이 없습니다" in window._status.text()
    assert window._connect_button.text() == "연결"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/gui/test_main_window.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'plotter.gui.main_window'`

- [ ] **Step 3: 메인 창 구현**

`plotter/gui/main_window.py`:

```python
"""메인 창: 카메라 미리보기, 촬영, 해칭 결과 확인, GRBL 전송."""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plotter import camera, gcode, grbl_sender, svg_export
from plotter.config import Config
from plotter.gui.preview import gray_to_qimage, render_lines
from plotter.gui.state import AppState, Controls, controls_for
from plotter.gui.workers import ProcessThread, SendThread
from plotter.lines import Polyline

PREVIEW_SIZE = (480, 360)
FRAME_INTERVAL_MS = 33
READY_MESSAGE = "스페이스바나 촬영 버튼으로 촬영하세요"
RESULT_PLACEHOLDER = "촬영하면 해칭 결과가 여기에 표시됩니다"


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, output_dir: Path, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("Plotter Path Generator")
        self._cfg = cfg
        self._output_dir = output_dir
        self._settings = settings or QSettings("TeslaPlotter", "PlotterPathGenerator")

        self._state = AppState.LIVE
        self._capture = None
        self._last_gray: np.ndarray | None = None
        self._image_size = (0, 0)
        self._lines: list[Polyline] = []
        self._commands: list[str] = []
        self._serial = None
        self._sender: grbl_sender.GrblSender | None = None
        self._worker = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_camera_frame)

        self._build_ui()
        self._refresh_ports()
        self._refresh_cameras()
        self._apply_state()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self._camera_combo = QComboBox()
        self._camera_combo.currentIndexChanged.connect(self._open_selected_camera)
        self._camera_refresh = self._button("새로고침", self._refresh_cameras)

        self._port_combo = QComboBox()
        self._port_refresh = self._button("새로고침", self._refresh_ports)
        self._connect_button = self._button("연결", self._toggle_connection)
        self._connection_label = QLabel()

        self._camera_view = self._view("카메라 준비 중")
        self._result_view = self._view(RESULT_PLACEHOLDER)

        self._capture_button = self._button("촬영 (Space)", self._capture_frame)
        self._retake_button = self._button("다시 촬영", self._retake)
        self._send_button = self._button("전송", self._send)
        self._pause_button = self._button("일시정지", self._toggle_pause)
        self._stop_button = self._button("정지", self._stop)

        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m 줄")
        self._progress.setValue(0)
        self._status = QLabel()

        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("카메라:"))
        camera_row.addWidget(self._camera_combo, 1)
        camera_row.addWidget(self._camera_refresh)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("포트:"))
        port_row.addWidget(self._port_combo, 1)
        port_row.addWidget(self._port_refresh)
        port_row.addWidget(self._connect_button)
        port_row.addWidget(self._connection_label)

        views = QHBoxLayout()
        views.addWidget(self._camera_view)
        views.addWidget(self._result_view)

        buttons = QHBoxLayout()
        for button in (self._capture_button, self._retake_button, self._send_button,
                       self._pause_button, self._stop_button):
            buttons.addWidget(button)

        layout = QVBoxLayout()
        layout.addLayout(camera_row)
        layout.addLayout(port_row)
        layout.addLayout(views)
        layout.addLayout(buttons)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Space"), self, activated=self._capture_frame)

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        # 버튼이 포커스를 가지면 스페이스바가 그 버튼을 누르므로 포커스를 받지 않게 한다
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        return button

    def _view(self, placeholder: str) -> QLabel:
        label = QLabel(placeholder)
        label.setFixedSize(*PREVIEW_SIZE)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid #888; background: #f4f4f4;")
        return label

    def _show_image(self, label: QLabel, image: QImage) -> None:
        label.setPixmap(QPixmap.fromImage(image).scaled(
            label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _set_status(self, message: str) -> None:
        self._status.setText(message)

    def _controls(self) -> Controls:
        return controls_for(
            self._state,
            camera_ready=self._capture is not None,
            port_connected=self._serial is not None,
            has_lines=bool(self._lines),
        )

    def _apply_state(self) -> None:
        c = self._controls()
        connected = self._serial is not None
        self._camera_combo.setEnabled(c.select_camera)
        self._camera_refresh.setEnabled(c.select_camera)
        self._port_combo.setEnabled(c.select_port and not connected)
        self._port_refresh.setEnabled(c.select_port and not connected)
        self._connect_button.setEnabled(c.select_port)
        self._connect_button.setText("연결 해제" if connected else "연결")
        self._connection_label.setText("● 연결됨" if connected else "● 연결 안 됨")
        self._capture_button.setEnabled(c.capture)
        self._retake_button.setEnabled(c.retake)
        self._send_button.setEnabled(c.send)
        self._pause_button.setEnabled(c.pause or c.resume)
        self._pause_button.setText("재개" if c.resume else "일시정지")
        self._stop_button.setEnabled(c.stop)

    # ---------- 카메라 ----------

    def _refresh_cameras(self) -> None:
        if self._state is not AppState.LIVE:
            return
        self._close_camera()
        indices = camera.list_cameras()
        self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        for index in indices:
            self._camera_combo.addItem(f"카메라 {index}", index)
        saved = self._settings.value("camera_index", -1, type=int)
        position = self._camera_combo.findData(saved)
        self._camera_combo.setCurrentIndex(position if position >= 0 else 0)
        self._camera_combo.blockSignals(False)
        if not indices:
            self._camera_view.setText("카메라 없음")
            self._set_status("카메라를 찾을 수 없습니다. 연결한 뒤 새로고침을 누르세요")
            self._apply_state()
            return
        self._open_selected_camera()

    def _open_selected_camera(self) -> None:
        index = self._camera_combo.currentData()
        if index is None:
            return
        self._close_camera()
        try:
            self._capture = camera.open_camera(index)
        except camera.CameraError as exc:
            self._set_status(str(exc))
            self._apply_state()
            return
        self._settings.setValue("camera_index", index)
        self._timer.start(FRAME_INTERVAL_MS)
        self._set_status(READY_MESSAGE)
        self._apply_state()

    def _close_camera(self) -> None:
        self._timer.stop()
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._last_gray = None

    def _update_camera_frame(self) -> None:
        if self._capture is None:
            return
        gray = camera.read_gray(self._capture)
        if gray is None:
            return
        self._last_gray = gray
        self._show_image(self._camera_view, gray_to_qimage(gray))

    # ---------- 촬영과 처리 ----------

    def _capture_frame(self) -> None:
        if not self._controls().capture or self._last_gray is None:
            return
        self._timer.stop()  # 촬영한 프레임이 미리보기에 남아 있게 한다
        gray = self._last_gray.copy()
        self._image_size = (gray.shape[1], gray.shape[0])
        self._state = AppState.PROCESSING
        self._set_status("이미지 처리 중... (potrace, Inkscape, 해칭)")
        self._apply_state()
        self._worker = ProcessThread(gray, self._cfg, self)
        self._worker.succeeded.connect(self._on_processed)
        self._worker.failed.connect(self._on_process_failed)
        self._worker.start()

    def _on_processed(self, lines: list[Polyline]) -> None:
        width, height = self._image_size
        self._lines = lines
        self._commands = gcode.generate(lines, width, height, self._cfg)
        self._show_image(self._result_view, render_lines(lines, width, height))
        self._state = AppState.REVIEW
        try:
            svg_export.save_svg(lines, width, height, self._output_dir / "output.svg")
            gcode.save_gcode(self._commands, self._output_dir / "output.gcode")
        except OSError as exc:
            self._set_status(f"파일 저장 실패: {exc}")
        else:
            if lines:
                self._set_status(f"선 {len(lines)}개 생성, output.svg와 output.gcode 저장됨. 전송을 누르면 그리기 시작")
            else:
                self._set_status("그릴 선이 없습니다. 다시 촬영하세요")
        self._apply_state()

    def _on_process_failed(self, message: str) -> None:
        self._retake()
        self._set_status(f"처리 실패: {message}")

    def _retake(self) -> None:
        self._lines = []
        self._commands = []
        self._result_view.clear()
        self._result_view.setText(RESULT_PLACEHOLDER)
        self._progress.setValue(0)
        self._state = AppState.LIVE
        if self._capture is not None:
            self._timer.start(FRAME_INTERVAL_MS)
            self._set_status(READY_MESSAGE)
        self._apply_state()

    # ---------- 시리얼 ----------

    def _refresh_ports(self) -> None:
        current = self._port_combo.currentText() or self._settings.value("port", "", type=str)
        ports = grbl_sender.available_ports()
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)
        self._apply_state()

    def _toggle_connection(self) -> None:
        if self._serial is not None:
            self._disconnect()
            self._set_status("연결을 해제했습니다")
            return
        name = self._port_combo.currentText()
        if not name:
            self._set_status("시리얼 포트를 선택하세요")
            return
        self._set_status(f"{name}에 연결 중...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._serial = grbl_sender.connect(name, self._cfg.baud)
        except grbl_sender.GrblError as exc:
            self._set_status(str(exc))
            self._apply_state()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._sender = grbl_sender.GrblSender(self._serial, self._cfg.pen_up)
        self._settings.setValue("port", name)
        self._set_status(f"{name}에 연결됨")
        self._apply_state()

    def _disconnect(self) -> None:
        if self._serial is not None:
            with contextlib.suppress(Exception):
                self._serial.close()
        self._serial = None
        self._sender = None
        self._apply_state()

    # ---------- 전송 ----------

    def _send(self) -> None:
        if not self._controls().send or self._sender is None:
            return
        self._progress.setRange(0, len(self._commands))
        self._progress.setValue(0)
        self._state = AppState.SENDING
        self._set_status("그리는 중...")
        self._apply_state()
        self._worker = SendThread(self._sender, self._commands, self)
        self._worker.progress.connect(lambda done, total: self._progress.setValue(done))
        self._worker.completed.connect(self._on_send_completed)
        self._worker.failed.connect(self._on_send_failed)
        self._worker.start()

    def _toggle_pause(self) -> None:
        if self._sender is None:
            return
        try:
            if self._state is AppState.SENDING:
                self._sender.pause()
                self._state = AppState.PAUSED
                self._set_status("일시정지됨")
            elif self._state is AppState.PAUSED:
                self._sender.resume()
                self._state = AppState.SENDING
                self._set_status("그리는 중...")
        except grbl_sender.GrblError as exc:
            self._set_status(str(exc))  # 전송 스레드도 같은 오류로 끝나며 _on_send_failed가 정리한다
            return
        self._apply_state()

    def _stop(self) -> None:
        if self._sender is None or self._state not in (AppState.SENDING, AppState.PAUSED):
            return
        self._sender.request_stop()
        self._stop_button.setEnabled(False)
        self._pause_button.setEnabled(False)
        self._set_status("정지하는 중... (펜을 올립니다)")

    def _on_send_completed(self, finished: bool) -> None:
        self._state = AppState.REVIEW
        self._set_status("그리기 완료" if finished else "정지했습니다. 펜을 올렸습니다")
        self._apply_state()

    def _on_send_failed(self, message: str) -> None:
        self._state = AppState.REVIEW
        self._disconnect()  # 다시 연결하면 GRBL 응답부터 다시 확인한다
        self._set_status(f"전송 실패: {message} (다시 연결하세요)")
        self._apply_state()

    # ---------- 종료 ----------

    def closeEvent(self, event) -> None:
        if self._state in (AppState.SENDING, AppState.PAUSED):
            answer = QMessageBox.question(self, "그리는 중", "그리기를 정지하고 종료할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._sender.request_stop()
        if self._worker is not None:
            self._worker.wait()
        self._close_camera()
        self._disconnect()
        event.accept()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/gui/test_main_window.py -v`
Expected: 5 passed

- [ ] **Step 5: 진입점 교체**

`main.py` 전체를 다음으로 바꾼다 (기존 스크립트 로직은 `plotter/processing.py`, `plotter/hatching.py`로 옮겨졌다):

```python
"""플로터 GUI 실행."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from plotter.config import ConfigError, load_config
from plotter.gui.main_window import MainWindow

ROOT = Path(__file__).parent


def main() -> int:
    app = QApplication(sys.argv)
    try:
        cfg = load_config(ROOT / "config.toml")
    except ConfigError as exc:
        QMessageBox.critical(None, "설정 오류", f"config.toml을 읽을 수 없습니다.\n\n{exc}")
        return 1
    window = MainWindow(cfg, ROOT)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: CLAUDE.md 갱신**

`CLAUDE.md` 전체를 다음으로 바꾼다:

````markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

The project is managed with `uv` (Python 3.12).

```powershell
uv sync                                        # install dependencies
uv run main.py                                 # launch the GUI
uv run pytest                                  # run all tests
uv run pytest tests/test_gcode.py::test_generate_empty_lines -v   # single test
```

GUI tests run headless via `QT_QPA_PLATFORM=offscreen` (set in `tests/gui/conftest.py`). The end-to-end processing test is skipped unless potrace and Inkscape are installed at the paths in `config.toml`.

## External requirements

- potrace and Inkscape executables (paths in `config.toml`, defaults `C:/potrace.exe` and `C:\Program Files\Inkscape\bin\inkscape.exe`).
- A webcam (opened with `cv2.CAP_DSHOW`) and an Arduino running GRBL on a COM port.

## Architecture

PyQt6 app that captures a webcam frame, hatches it, writes `output.svg` / `output.gcode` to the repo root, and streams the G-code to GRBL.

Data passed between stages is always `list[Polyline]` (`plotter/lines.py`), in image pixel coordinates until `gcode.to_mm` converts to plotter millimetres (aspect-preserving fit, y flipped, origin bottom-left).

Pipeline: `processing.process` (blur → adaptive threshold → morph open → potrace → Inkscape → blend with original) → `hatching.hatch_image` → `svg_export.save_svg` and `gcode.generate` (strokes ordered nearest-first by `lines.order_lines`) → `grbl_sender.GrblSender.stream`.

- `hatching.py` is a port of the `hatched` library's `_build_hatch`; `hatched` 0.2.0 itself is incompatible with shapely 2.2 and is not a dependency.
- `grbl_sender` uses send-and-wait-for-`ok`. It finishes with `G4 P0` so completion means motion actually finished. Stop/error = feed hold `!` → soft reset `0x18` → pen-up command. `connect` requires the GRBL banner before returning, so non-GRBL devices are rejected.
- GUI: `gui/state.py` is the single source of truth for which controls are enabled in each `AppState`; `gui/workers.py` runs processing and streaming in `QThread`s; `gui/main_window.py` wires it together. Pause/stop are called from the GUI thread while `stream` runs in a worker; serial writes are guarded by a lock.
- All hardware boundaries take injectable factories (`capture_factory`, `serial_factory`) so tests use fakes.
- Pen commands, work area, feed rate and hatching parameters live in `config.toml`. The firmware/pen mechanism is not confirmed; defaults assume servo GRBL (`M3 S90` / `M5`). Unknown keys or wrong types raise `ConfigError`.
- User-facing strings and code comments are Korean.
````

- [ ] **Step 7: 전체 테스트**

Run: `uv run pytest -v`
Expected: 80 passed (potrace와 Inkscape가 없으면 79 passed, 1 skipped)

- [ ] **Step 8: 수동 확인 (실제 장비)**

`uv run main.py`로 실행해 확인한다:

1. 카메라 드롭다운에 연결된 카메라가 나오고, 바꾸면 미리보기가 바뀐다.
2. 스페이스바와 `촬영` 버튼 둘 다 촬영된다. 처리 중에는 모든 버튼이 꺼진다.
3. 오른쪽에 해칭 결과가 나오고, 프로젝트 루트에 `output.svg`와 `output.gcode`가 생긴다.
4. 렌즈를 가리고 촬영하면 "그릴 선이 없습니다"가 나오고 `전송`이 꺼져 있다.
5. GRBL이 아닌 포트에 `연결`하면 약 6초 안에 "GRBL 응답이 없습니다"가 나온다.
6. GRBL 아두이노에 연결하고 `전송`하면 진행률이 올라간다. `일시정지`를 누르면 멈추고 버튼이 `재개`로 바뀐다. `정지`를 누르면 펜이 올라가고 결과 확인 상태로 돌아간다.
7. 그리는 도중 USB를 뽑으면 "전송 실패: 시리얼 연결이 끊겼습니다"가 나오고 연결 해제 상태가 된다.
8. 프로그램을 다시 실행하면 마지막에 고른 카메라와 포트가 선택되어 있다.
9. `config.toml`에 `feedrate = 1`을 넣고 실행하면 "알 수 없는 설정 항목: feedrate" 대화상자가 뜬다.

- [ ] **Step 9: Commit**

```powershell
git add plotter/gui/main_window.py tests/gui/test_main_window.py main.py CLAUDE.md
git commit -m "feat: add PyQt6 main window and replace script entry point"
```
