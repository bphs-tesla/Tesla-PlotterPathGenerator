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
