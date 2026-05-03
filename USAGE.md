# Ray5W Laser Control – User Guide

A step-by-step guide to installing, launching, and using the Ray5W laser
control software.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Launching the Application](#launching-the-application)
4. [Application Layout](#application-layout)
5. [Writing or Loading a G-code Program](#writing-or-loading-a-g-code-program)
   - [Write G-code manually](#write-g-code-manually)
   - [Open an existing G-code file](#open-an-existing-g-code-file)
   - [Import a design file](#import-a-design-file)
6. [Running a Program](#running-a-program)
7. [Monitoring a Job](#monitoring-a-job)
8. [Stopping a Job](#stopping-a-job)
9. [Using the Design Tools](#using-the-design-tools)
   - [Material Library](#material-library)
   - [Path Offset (Kerf Compensation)](#path-offset-kerf-compensation)
   - [Array / Grid](#array--grid)
   - [Auto-Nest on Sheet](#auto-nest-on-sheet)
   - [Image Trace](#image-trace)
10. [AI Path Optimisation](#ai-path-optimisation)
11. [3-D Engraving Simulation](#3-d-engraving-simulation)
12. [Batch Job Queue](#batch-job-queue)
13. [Job Cost Estimator](#job-cost-estimator)
14. [Advanced Settings](#advanced-settings)
15. [Plugins](#plugins)
16. [Keyboard Shortcuts](#keyboard-shortcuts)

---

## Requirements

| Requirement | Details |
|---|---|
| **Python** | 3.9 or newer |
| **tkinter** | Included in most Python distributions |
| **Third-party packages** | None – no `pip install` needed |

---

## Installation

### Linux (Ubuntu / Debian / Mint) – automated

```bash
bash install.sh
```

The script checks your Python version and installs `python3-tk` via `apt`.

### Linux – manual

```bash
sudo apt install python3-tk
```

### macOS

`tkinter` ships with the official Python installer from python.org.  No extra
steps are needed.

### Windows

`tkinter` is bundled with the standard Python Windows installer.  No extra
steps are needed.

---

## Launching the Application

From the repository root, run:

```bash
python3 run_laser.py
```

The **Ray5W Laser Control** window (1 400 × 800 px) will open with a sample
40 × 40 mm square outline pre-loaded in the editor.

---

## Application Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Menu bar:  File  Laser  Design  Tools  Help                    │
├───────────────────────────────────────────────────────────────  │
│  Toolbar:  ▶ Run  ■ Stop  ⟳ Reset  ⊞ Fit   Open  Save  Import…│
├──────────────┬──────────────────────────┬───────────────────────┤
│  G-CODE      │  BURN PATH (XY canvas)   │  Right panel tabs:    │
│  PROGRAM     │                          │  • Status             │
│  (editor)    │  Drag to pan             │  • Design             │
│              │  Scroll to zoom          │  • Simulate           │
│              │  F to fit all            │  • Queue              │
│              │                          │  • Cost               │
└──────────────┴──────────────────────────┴───────────────────────┘
│  MDI bar (single-line G-code command input)                      │
└─────────────────────────────────────────────────────────────────┘
```

| Panel | Purpose |
|---|---|
| **G-code editor** (left) | Write or paste G-code; full undo/redo support |
| **Burn path canvas** (centre) | Real-time XY visualisation of all moves |
| **Status tab** (right) | Live position, laser state, power, feed rate |
| **Design tab** (right) | Material library, design tools, image trace |
| **Simulate tab** (right) | 3-D depth-map simulation after a run |
| **Queue tab** (right) | Batch job queue |
| **Cost tab** (right) | Job cost estimator |

---

## Writing or Loading a G-code Program

### Write G-code manually

Click anywhere in the **G-CODE PROGRAM** editor on the left and type standard
GRBL G-code.  A sample program is pre-loaded on startup to get you started.

### Open an existing G-code file

- **Menu:** `File → Open G-code…`  *(Ctrl+O)*
- **Toolbar:** click **Open**

A file dialog will appear.  Select any plain-text `.gcode`, `.nc`, or `.txt`
file.  The contents replace the current editor text.

### Save the current program

- **Menu:** `File → Save G-code…`  *(Ctrl+S)*
- **Toolbar:** click **Save**

### Import a design file

The software can convert vector and raster files to G-code automatically.

| Source | Menu path |
|---|---|
| **SVG** vector | `File → Import → SVG vector…` |
| **DXF** drawing | `File → Import → DXF drawing…` |
| **PNG / BMP** raster image | `File → Import → Raster image (PNG/BMP)…` |

After import the generated G-code appears in the editor and the burn path is
redrawn on the canvas.

---

## Running a Program

1. Make sure the G-code program is loaded in the editor.
2. Press **F5** or click **▶ Run** in the toolbar (or `Laser → Run Program`).
3. The machine state changes to **RUNNING** and the canvas updates in real time
   as each block is executed.
4. When the program finishes the status changes to **IDLE** and a completion
   message is logged.

> **Tip:** Enable `Laser → Live Preview` (checked by default) to see the burn
> path update every 20 blocks while running.

---

## Monitoring a Job

Switch to the **Status** tab on the right panel at any time during a run:

| Field | Description |
|---|---|
| **POSITION X / Y** | Current head position in mm (or inches) |
| **STATUS** | `IDLE`, `RUNNING`, or `ALARM` |
| **LASER** | `ON (CONSTANT)` / `ON (DYNAMIC)` / `OFF` |
| **POWER** | Current S value and percentage of maximum (0–1000) |
| **FEED** | Current feed rate in mm/min |
| **UNITS** | Metric (mm) or Inch |
| **MODE** | Absolute or Incremental |

The **MESSAGE LOG** at the bottom of the Status tab records all execution
events and any error alerts raised by the watchdog.

---

## Stopping a Job

- **Emergency stop:** press **F6** or click **■ Stop** in the toolbar.
  The machine enters `ALARM` state immediately.
- **Reset after stop:** click **⟳ Reset** or choose `Laser → Reset Machine`
  to clear the alarm and return to `IDLE`.

---

## Using the Design Tools

Open the **Design** tab on the right panel.

### Material Library

1. Select a preset from the list (Birch Ply, MDF, Acrylic, Cardboard, etc.).
2. Click **Apply** to automatically set power, speed, pass count, and dithering
   mode on the machine.
3. To save your own preset, fill in the fields at the bottom and click **Add**.
4. Select a custom preset and click **Delete** to remove it.

Presets are stored in `~/.lazerem/materials.json` and persist between sessions.

### Path Offset (Kerf Compensation)

1. In the **Design Tools** sub-tab, enter an offset distance in mm
   (positive = expand, negative = shrink).
2. Click **Offset** (or use `Design → Offset Path…`).
3. The G-code in the editor is updated with the offset path.

### Array / Grid

1. Enter the number of columns and rows, and the X/Y spacing in mm.
2. Click **Array** (or use `Design → Array / Grid…`).
3. A tiled version of the current design is written to the editor.

### Auto-Nest on Sheet

1. Enter the sheet width, height, and the margin/gap between parts.
2. Click **Nest** (or use `Design → Auto-Nest on Sheet…`).
3. The software packs copies of the design into the sheet using shelf-first-fit
   bin packing and updates the editor.

### Image Trace

1. Switch to the **Image Trace** sub-tab.
2. Choose a dithering mode: `threshold`, `floyd-steinberg`, or `jarvis`.
3. Adjust brightness, contrast, and saturation sliders.
4. Click **Trace** and select your PNG or BMP image.
5. The traced G-code is inserted into the editor.

---

## AI Path Optimisation

1. Choose `Tools → Optimize Path (AI)…`.
2. Select one or more optimisation strategies:
   - **Nearest-Neighbour TSP** – reorders moves to minimise total rapid travel.
   - **Inner-First Sort** – cuts inner shapes before outer ones.
   - **Collinear Merge** – removes redundant mid-points from straight runs.
3. Click **OK**.  The editor is updated with the optimised G-code.

---

## 3-D Engraving Simulation

After running a program, switch to the **Simulate** tab:

1. Click **⟳ Re-Simulate** to render the depth map from the last burn path.
2. The canvas shows a relief view coloured from light tan (no burn) through
   dark brown / near-black (deep engrave), with normal-map shading.
3. Click **✗ Clear** to reset the simulation canvas.

---

## Batch Job Queue

Switch to the **Queue** tab to run multiple files in sequence.

1. Load a G-code program in the editor and click **+ Add** in the Queue panel
   (or choose `Tools → Batch Queue`).
2. Optionally override the power, speed, or pass count per job.
3. Reorder jobs with the **↑** / **↓** buttons.
4. Click **Run All** to execute every queued job in order, or **Run Next** to
   run just the first pending job.
5. Per-job elapsed time and status (`Pending`, `Running`, `Done`) are shown in
   the list.
6. Click **Reset** to mark all completed jobs as pending again for a second run.

---

## Job Cost Estimator

Switch to the **Cost** tab (or choose `Tools → Estimate Job Cost`).

After running a program:

1. Click **Calculate** to analyse the last burn path.
2. Review the estimates:
   - Estimated run time
   - Engraved area (cm²)
   - Energy consumed (Wh) and electricity cost
   - Material cost
3. Adjust the configuration values (machine wattage, cost/kWh, material
   cost/cm², currency) and recalculate as needed.

---

## Advanced Settings

The **Status** tab contains an **ADVANCED SETTINGS** sub-section:

| Setting | Description |
|---|---|
| **PASSES** | Repeat the entire program N times (1–99) |
| **DITHERING** | `none` / `threshold` / `floyd-steinberg` / `jarvis` |
| **CONTROLLER** | `GRBL` / `Marlin` / `Ruida` |

Changes take effect on the next **Run**.

---

## Plugins

Drop a Python `.py` file into `~/.lazerem/plugins/`.  Supported hooks:

| Hook | When it fires |
|---|---|
| `on_load` | Application startup |
| `on_run_start` | Before a program begins |
| `on_run_end` | After a program finishes |
| `on_gcode_import` | After a design file is imported |
| `on_block` | After each G-code block is executed |

- **Reload without restart:** `Tools → Reload Plugins`
- **View loaded plugins and errors:** `Tools → Plugin Info…`

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **Ctrl+N** | New program (clear editor) |
| **Ctrl+O** | Open G-code file |
| **Ctrl+S** | Save G-code file |
| **Ctrl+Q** | Quit |
| **F5** | Run program |
| **F6** | Stop / Emergency stop |
| **F** or **f** | Fit burn path to canvas view |
| **Scroll wheel** | Zoom canvas in/out |
| **Click + drag** | Pan canvas |
