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
