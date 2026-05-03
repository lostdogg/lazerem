# Ray5W Laser Control

A Python 3 + Tkinter application for the **Ray5W diode laser engraver**.
Simulates GRBL-style G-code execution, visualises the burn path, and
provides a rich design-editing and import pipeline — all with **zero
third-party dependencies**.

---

## Features

### Core G-code Control
| Code | Function |
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
  groups with transforms; Bézier curves approximated as polylines; px→mm scaling.
- **DXF import** – LINE, ARC, CIRCLE, LWPOLYLINE, POLYLINE, SPLINE entities.
- **Raster image import** – PNG (tkinter) and BMP (pure-Python parser).
- **Image tracing** – three dithering modes: `threshold`, `floyd-steinberg`, `jarvis`.
- **Image adjustments** – brightness, contrast, saturation.
- **Path offset** – kerf compensation (expand / shrink polygon by fixed distance).
- **Array / grid** – tile a design in an N×M grid.
- **Auto-nesting** – shelf-first-fit bin packing.
- **Boolean union** – combine multiple design paths.

### Layer Effects
- **Gradient fill** – horizontal or vertical boustrophedon raster with power
  ramping linearly from one side to the other.
- **Variable power curve** – follow a polyline while modulating S according to
  an arbitrary Python callable of arc-length fraction.
- **Texture fill** – repeating dot / line / cross grid fill inside a rectangle.

### AI Path Optimisation
- **Nearest-neighbour TSP** reordering – reduces total rapid-travel distance.
- **Inner-first sort** – cut smaller (inner) shapes before outer ones to prevent
  loose piece shifting.
- **Collinear segment merge** – remove redundant mid-points from polylines.

### Material Library
- 8 built-in presets (Birch Ply, MDF, Acrylic, Cardboard, Leather, Photo
  Engrave, Anodised Aluminium, …).
- Add, edit, delete presets; saved to `~/.lazerem/materials.json`.
- One-click apply sets power, speed, passes, and dithering mode.

### Machine Settings
- **Pass count** – repeat the program N times automatically.
- **Dithering mode** – selected per run (none / threshold / Floyd-Steinberg / Jarvis).
- **Controller type** – GRBL / Marlin / Ruida.
- **Live preview** – canvas updates every 20 G-code blocks while running.

### 3-D Engraving Simulation
- After a run, the **Simulate** tab shows a depth-map view coloured by
  accumulated laser energy: light tan (raw wood) → dark brown / near-black
  (deep engrave).
- Normal-map shading gives a 3-D relief appearance.
- Configurable resolution (mm per cell) and depth-per-pass parameters.

### Batch Processing Queue
- Queue multiple G-code jobs with individual power / speed / pass overrides.
- Run all jobs in sequence with *Run All*, or one at a time with *Run Next*.
- Reorder with ↑/↓, reset statuses to re-run, per-job elapsed time display.

### Job Cost Estimator
- Estimates time, engraved area, electricity (Wh and cost), and material cost.
- Configurable: machine wattage, cost/kWh, material cost/cm², beam width,
  rapid speed, currency.
- Reads directly from the machine burn-path after a run.

### Real-Time Error Detection
- Background watchdog thread checks during program execution.
- Built-in checks: **OVERTRAVEL** (position outside work area), **THERMAL**
  (accumulated power × time exceeds limit), **STALL** (no position change
  while running), **JOB_INTERRUPTION** (ALARM state), **LOW_POWER**
  (laser armed but S=0).
- Alerts are deduplicated and logged to the message panel.

### Multi-Machine Network Control
- `NetworkController` manages a fleet of `MachineNode` instances.
- **dispatch** – send a job to the first idle node; pending queue for when
  all nodes are busy.
- **broadcast** – send the same job to every node simultaneously.
- Each node runs its job in a background thread; callbacks on completion.

### Plugin / Extension System
- Drop a Python `.py` file into `~/.lazerem/plugins/`.
- Supported hooks: `on_load`, `on_run_start`, `on_run_end`, `on_gcode_import`,
  `on_block`.
- *Tools → Reload Plugins* discovers new plugins without restarting.
- *Tools → Plugin Info* lists loaded plugins and any load errors.

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
pytest
```

245 tests covering the parser, machine, design operations, importers, image
processor, simulation, plugin manager, job queue, network control, error
monitor, layer effects, path optimiser, and cost estimator.

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
  simulation.py        – 3-D engraving depth-map model
  job_queue.py         – Batch processing queue
  cost_estimator.py    – Job time/material/electricity cost calculator
  error_monitor.py     – Real-time watchdog (overtravel, thermal, stall, …)
  network_control.py   – Multi-machine fleet manager
  layer_effects.py     – Gradient fill, variable power curve, texture fill
  path_optimizer.py    – Nearest-neighbour TSP, inner-first sort, segment merge
  plugin_manager.py    – Plugin discovery, loading, hook dispatch
  importers/
    svg_importer.py    – SVG → G-code
    dxf_importer.py    – DXF → G-code
  ui/
    app.py             – Main Tkinter window
    canvas.py          – Burn-path canvas widget
    panels.py          – Coordinate / status / settings panels
    design_panel.py    – Material library + design tools notebook panel
    simulation_canvas.py – 3-D depth-map canvas widget
    job_queue_panel.py – Batch job queue UI panel
    cost_panel.py      – Job cost estimator UI panel
```
