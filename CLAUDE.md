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

GUI tests run headless via `QT_QPA_PLATFORM=offscreen` (set in `tests/gui/conftest.py`). The end-to-end processing test is skipped unless the potrace executable at `potrace_path` exists.

## External requirements

- potrace executable (`potrace_path` in `config.toml`, default `./potrace/potrace.exe`; relative paths resolve from the project folder via `processing.tool_path`, and `potrace/` is git-ignored — download the Windows build into it). Inkscape is not needed: potrace's SVG is rasterized in-process with PyQt6 `QSvgRenderer` (`processing.render_svg`).
- A webcam (opened with `cv2.CAP_DSHOW`) and an Arduino running GRBL on a COM port.

## Architecture

PyQt6 app that captures a webcam frame, hatches it, writes `output/output-YYYYMMDD-HHMMSS.svg` and `.gcode` (one pair per capture, folder created on demand, git-ignored), and streams the G-code to GRBL.

Data passed between stages is always `list[Polyline]` (`plotter/lines.py`), in image pixel coordinates until `gcode.to_mm` converts to plotter millimetres (aspect-preserving fit, y flipped, origin bottom-left).

Pipeline: `processing.process` (blur → adaptive threshold → morph open → potrace → `render_svg` (PyQt6) → blend with original) → `hatching.hatch_image` → `svg_export.save_svg` and `gcode.generate` (strokes ordered nearest-first by `lines.order_lines`) → `grbl_sender.GrblSender.stream`.

- `maze.py`: the 미로 생성 button skips camera/processing entirely. `generate_maze` (mazelib Prims, min 3×3 cells, entrances punched into the grid since mazelib only reports them) → `maze_to_lines` turns wall cells between even-index posts into merged horizontal/vertical lines (`CELL_PX` per cell) → `maze_drawing` adds an inward arrow at the entrance (leftmost opening) and an outward arrow at the exit, shifting everything by a one-cell margin so the arrows fit → same `_on_processed` path as a capture (preview, output files, 전송). mazelib has no image/SVG export of its own.
- `hatching.py` is a port of the `hatched` library's `_build_hatch`; `hatched` 0.2.0 itself is incompatible with shapely 2.2 and is not a dependency.
- `grbl_sender` uses send-and-wait-for-`ok`. It finishes with `G4 P0` so completion means motion actually finished. While waiting for `ok` it polls status `?`; any `<...>` report resets the 30 s response timeout, so long strokes at slow feed rates do not abort. Stop/error = feed hold `!` → poll `?` until `Hold:0`/`Idle` (max 10 s) → soft reset `0x18` → pen-up command; if pen-up is not acknowledged (e.g. ALARM after reset) a `GrblError` is raised instead of reporting success. `connect` requires the GRBL banner before returning, so non-GRBL devices are rejected.
- GUI: `gui/state.py` is the single source of truth for which controls are enabled in each `AppState`; `gui/workers.py` runs processing, GRBL connect (Bluetooth COM ports can take 10+ s to open) and streaming in `QThread`s; `gui/main_window.py` wires it together. Pause/stop are called from the GUI thread while `stream` runs in a worker; serial writes are guarded by a lock.
- All hardware boundaries take injectable factories (`capture_factory`, `serial_factory`) so tests use fakes.
- Pen commands, work area, feed rate and hatching parameters live in `config.toml`. The firmware/pen mechanism is not confirmed; defaults assume servo GRBL (`M3 S90` / `M5`). Unknown keys or wrong types raise `ConfigError`.
- User-facing strings and code comments are Korean.
