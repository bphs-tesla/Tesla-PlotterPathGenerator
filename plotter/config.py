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
