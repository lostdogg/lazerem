# lazerem – Ray5W Laser Control

A GRBL-style G-code interpreter and burn-path visualiser for the
**Ray5W diode laser engraver**, built with Python 3 + tkinter.
Modelled after the Fanuc CNC emulator pattern – same layout, same
workflow, but adapted for 2-axis laser engraving / cutting.

---

## Features

| Feature | Details |
|---|---|
| **G-code editor** | Syntax-friendly text editor with undo/redo |
| **Burn-path viewer** | 2-D XY canvas with zoom (scroll wheel) and pan (drag) |
| **Laser status panel** | Live position (X Y), laser state, power %, feed rate |
| **MDI (Manual Data Input)** | Execute single G-code lines interactively |
| **Message log** | Execution messages, alarms, and status updates |
| **Open / Save programs** | Load `.nc`, `.gcode`, `.ngc`, `.gc`, `.txt` files |
| **Power-tinted paths** | Cut lines shaded orange → yellow by laser power level |

### Supported G/M codes

| Code | Description |
|---|---|
| G00 | Rapid positioning (laser off) |
| G01 | Linear cut / engrave |
| G02 / G03 | Circular interpolation (CW / CCW) |
| G04 | Dwell (P = ms) |
| G20 / G21 | Inch / Metric units |
| G90 / G91 | Absolute / Incremental mode |
| M3 | Laser ON – constant-power mode |
| M4 | Laser ON – dynamic-power mode (GRBL laser mode) |
| M5 | Laser OFF |
| M2 / M30 | End of program |
| S | Laser power (0–1000, GRBL default) |
| F | Feed rate (mm/min) |

---

## Requirements

- Linux (Ubuntu 20.04+ / Debian 11+ / Mint 20+), macOS, or Windows
- Python 3.8+
- `python3-tk` system package (tkinter)

No third-party Python packages are required.

---

## Installation

```bash
git clone https://github.com/lostdogg/lazerem.git
cd lazerem
chmod +x install.sh
./install.sh
```

---

## Running

```bash
python3 run_laser.py
```

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| **F5** | Run program |
| **F6** | Stop / Emergency laser off |
| **F** | Fit burn path in view |
| **Ctrl+O** | Open G-code file |
| **Ctrl+S** | Save G-code file |
| **Ctrl+N** | New program |
| **Ctrl+Q** | Quit |
| **Scroll wheel** | Zoom canvas |
| **Drag** | Pan canvas |
| **Enter** (MDI bar) | Execute MDI line |

---

## Project Layout

```
lazerem/
├── lazerem/
│   ├── __init__.py
│   ├── main.py          # Entry point
│   ├── parser.py        # G-code parser
│   ├── machine.py       # Laser machine simulation
│   └── ui/
│       ├── __init__.py
│       ├── app.py       # Main application window
│       ├── canvas.py    # Burn-path canvas widget
│       └── panels.py    # Position & laser-status panels
├── tests/
│   ├── test_parser.py
│   └── test_machine.py
├── run_laser.py         # Top-level launcher
├── install.sh           # Linux setup script
└── pytest.ini
```

---

## Running Tests

```bash
pip install pytest      # one-time
python -m pytest
```

---

## Sample G-code

```gcode
; Ray5W sample – 40 x 40 mm square outline
G21 G90             ; metric, absolute
G0 X0 Y0            ; move to origin (laser off)
M3 S500             ; laser on, 50% power
G1 X40 F3000        ; cut right
G1 Y40              ; cut up
G1 X0               ; cut left
G1 Y0               ; cut down
M5                  ; laser off
G0 X0 Y0            ; return to origin
M2                  ; end
```