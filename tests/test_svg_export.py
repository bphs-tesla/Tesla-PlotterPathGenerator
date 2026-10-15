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
