#!/usr/bin/env bash
# lazerem.sh – cross-platform launcher for Lazerem (Ray5W Laser Control)
# Works from any directory, including a USB drive.
#
# Usage:  ./lazerem.sh [extra args passed to run_laser.py]

set -e

# Change to the directory that contains this script so relative imports work.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Locate a Python 3 interpreter that includes tkinter ───────────────────
find_python() {
    for PY in python3 python3.12 python3.11 python3.10 python3.9 python; do
        if command -v "$PY" &>/dev/null; then
            VER=$("$PY" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            if [ "$VER" = "3" ]; then
                if "$PY" -c "import tkinter" &>/dev/null 2>&1; then
                    echo "$PY"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

PY=$(find_python || true)

if [ -z "$PY" ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ERROR: Python 3 with tkinter was not found on this system."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Install Python 3 + tkinter:"
    echo "    Ubuntu / Debian / Mint:  sudo apt install python3 python3-tk"
    echo "    Fedora / RHEL:           sudo dnf install python3 python3-tkinter"
    echo "    Arch Linux:              sudo pacman -S python tk"
    echo "    macOS (Homebrew):        brew install python-tk"
    echo "    macOS (python.org):      Download from https://www.python.org/downloads/"
    echo ""
    exit 1
fi

exec "$PY" run_laser.py "$@"
