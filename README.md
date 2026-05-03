# Ray5W Laser Control

A Python 3 + Tkinter application for the **Ray5W diode laser engraver**.
Simulates GRBL-style G-code execution, visualises the burn path, and
provides a rich design-editing and import pipeline — all with **zero
third-party dependencies**.

---

## Features

### Core G-code Control
| | |
|---|---|
| G0 | Rapid positioning (laser off) |
| G1 | Linear cut / engrave |
| G2 / G3 | Circular arcs CW / CCW |
| G4 | Dwell |
| G20 / G21 | Inch / Metric units |
| G90 / G91 | Absolute / Incremental positioning |
| M3 | Laser ON – constant-power mode |
| M4 | Laser ON – dynamic-power mode |
| M5 | Laser OFF |
| S | Laser power 0–1000 |
| F | Feed rate (mm/min) |
| M2 / M30 | End of program |

### Design Editing
- **SVG import** – paths, rects, circles, ellipses, lines, polylines/polygons,
  groups with transforms (translate/scale/rotate/matrix); Bézier curves
  approximated as line segments; automatic px→mm scaling.
- **DXF import** – LINE, ARC, CIRCLE, LWPOLYLINE, POLYLINE/VERTEX, SPLINE
  entities from ASCII DXF files.
- **Raster image import** – PNG (via tkinter) and BMP (pure-Python parser);
  converted to raster engrave G-code.
- **Image tracing** – three dithering modes:
  - `threshold` – hard cutoff
  - `floyd-steinberg` – error-diffusion (recommended for photos)
  - `jarvis` – Jarvis-Judice-Ninke (highest quality)
- **Image adjustments** – brightness, contrast, saturation (all in pure Python).
- **Path offset** – expand or shrink a design by a fixed distance (kerf compensation).
- **Array / grid** – duplicate a design in an N×M grid with configurable spacing.
- **Auto-nesting** – shelf-first-fit bin packing to minimise waste on a sheet.
- **Boolean union** – combine multiple design paths into one program.

### Material Library
- 8 built-in presets (Birch Ply, MDF, Acrylic, Cardboard, Leather, Photo Engrave, …).
- Add, edit, and delete presets; saved to `~/.lazerem/materials.json`.
- One-click apply sets power, speed, passes, and dithering mode.

### Machine Settings
- **Pass count** – repeat the program N times automatically.
- **Dithering mode** – selected per run (none / threshold / Floyd-Steinberg / Jarvis).
- **Controller type** – GRBL / Marlin / Ruida (affects output labelling; full
  protocol adapters are a future enhancement).
- **Live preview** – canvas updates every 20 G-code blocks while running.

### UI
- Dark "engraver green" theme.
- Left pane: G-code editor with undo/redo.
- Centre pane: zoomable, pannable burn-path canvas (rapid = dashed red,
  cut = orange→yellow by power, arcs = blue/purple).
- Right pane: Status tab (position, laser, advanced settings, message log)
  and Design tab (material library, design tools, image trace).
- Toolbar shortcuts for import (SVG / DXF / image).
- MDI bar for single-line command entry.

---

## Running

```bash
python3 run_laser.py
```

### Requirements

- Python 3.9+
- `tkinter` (included in most Python distributions; on Debian/Ubuntu:
  `sudo apt install python3-tk`)

No pip packages required.

---

## Testing

```bash
python -m pytest
```

120 tests covering the parser, machine, design operations, importers, and
image processor.

---

## File Layout

```
lazerem/
  __init__.py
  machine.py           – LaserMachine (G-code execution, burn-path recording)
  parser.py            – GRBL G-code tokeniser / block parser
  design.py            – DesignPath, offset, array, nesting, boolean ops
  material_library.py  – JSON-backed material preset library
  image_processor.py   – PNG/BMP loading, brightness/contrast/saturation, trace
  importers/
    svg_importer.py    – SVG → G-code
    dxf_importer.py    – DXF → G-code
  ui/
    app.py             – Main Tkinter window
    canvas.py          – Burn-path canvas widget
    panels.py          – Coordinate / status / settings panels
    design_panel.py    – Material library + design tools notebook panel
```
