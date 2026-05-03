#!/usr/bin/env bash
# install.sh – set up Ray5W laser control on Linux (Ubuntu / Debian / Mint)
set -e

PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=8

# ── Check Python version ──────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Please install Python 3.8+."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt "$PYTHON_MIN_MAJOR" ] || \
   { [ "$PY_MAJOR" -eq "$PYTHON_MIN_MAJOR" ] && [ "$PY_MINOR" -lt "$PYTHON_MIN_MINOR" ]; }; then
    echo "ERROR: Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ is required (found $PY_VER)."
    exit 1
fi

echo "✓ Python $PY_VER found."

# ── Install tkinter ───────────────────────────────────────────────────────
echo "Installing python3-tk (tkinter) …"
sudo apt-get install -y python3-tk

echo ""
echo "✓ Installation complete."
echo ""
echo "Run the laser control with:"
echo "  python3 run_laser.py"
