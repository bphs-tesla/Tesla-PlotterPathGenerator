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


def test_inkscape_path_is_no_longer_a_setting(tmp_path):
    # SVG는 PyQt6로 그리므로 Inkscape 경로를 받지 않는다
    with pytest.raises(ConfigError, match="inkscape_path"):
        load_config(write(tmp_path, "inkscape_path = 'C:/inkscape.exe'\n"))
