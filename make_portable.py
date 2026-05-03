#!/usr/bin/env python3
"""
make_portable.py – Create a self-contained USB-portable bundle of Lazerem.

Usage
-----
    python3 make_portable.py [--dest <output-dir>]

The script copies all application source files into a single folder
(default: dist/lazerem-portable/) together with platform launchers and a
plain-text README so the bundle can be dropped onto a USB drive and run on
any machine that has Python 3 + tkinter.

Because Lazerem has zero third-party package dependencies the bundle is
just source code – no virtualenv or wheel files are needed.

Output layout
-------------
    <dest>/
        run_laser.py          – entry point (python3 run_laser.py)
        lazerem.sh            – Linux / macOS double-click / shell launcher
        lazerem.bat           – Windows double-click launcher
        install_check.py      – quick self-test (verifies Python + tkinter)
        lazerem/              – full package source
        README.txt            – quick-start guide for USB users
"""

import argparse
import os
import shutil
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy *src* into *dst*, skipping __pycache__ and .pyc files."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "__pycache__" or item.suffix == ".pyc":
            continue
        target = dst / item.name
        if item.is_dir():
            copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def make_readme(dest: Path) -> None:
    content = textwrap.dedent("""\
        Lazerem – Ray5W Laser Control (Portable Edition)
        =================================================

        This folder contains a self-contained copy of Lazerem.
        Copy the entire folder to a USB drive or any computer.

        ── Quick Start ──────────────────────────────────────────────────────

        Windows
          1. Make sure Python 3.9+ is installed (see INSTALL section below).
          2. Double-click  lazerem.bat
             or open a Command Prompt here and run:
               python run_laser.py

        Linux / macOS
          1. Make sure Python 3.9+ with tkinter is installed (see INSTALL).
          2. Open a terminal in this folder and run:
               chmod +x lazerem.sh && ./lazerem.sh
             or directly:
               python3 run_laser.py

        ── INSTALL: Python 3 + tkinter ──────────────────────────────────────

        Windows
          • Download Python 3.12 from https://www.python.org/downloads/
          • On the first installer screen check:
              [✓] Add Python to PATH
          • Click "Customize installation" → "Optional Features" and ensure:
              [✓] tcl/tk and IDLE   ← this is tkinter

        Ubuntu / Debian / Mint
          sudo apt update && sudo apt install python3 python3-tk

        Fedora / RHEL / CentOS
          sudo dnf install python3 python3-tkinter

        Arch Linux
          sudo pacman -S python tk

        macOS (Homebrew)
          brew install python-tk
          # then run with: python3 run_laser.py

        macOS (official installer)
          • Download from https://www.python.org/downloads/
          • The macOS pkg includes tkinter automatically.

        ── Self-test ─────────────────────────────────────────────────────────

        Run this to verify your Python environment before starting Lazerem:
          python3 install_check.py        (Linux / macOS)
          python install_check.py         (Windows)

        ── No internet required ──────────────────────────────────────────────

        Lazerem has zero third-party package dependencies.
        Once Python + tkinter are installed no further downloads are needed.

        ── USB Tips ──────────────────────────────────────────────────────────

        • Materials and settings are stored in ~/.lazerem/ on the HOST
          machine, not on the USB drive.  This keeps the USB read-only
          friendly and avoids permission issues on shared computers.

        • The launchers (lazerem.sh / lazerem.bat) use the Python that is
          already installed on the host – no Python is bundled.

        • If the host machine does not have Python, follow the INSTALL
          section above.  A one-time install is all that is needed.
    """)
    (dest / "README.txt").write_text(content, encoding="utf-8")


def make_install_check(dest: Path) -> None:
    content = textwrap.dedent("""\
        #!/usr/bin/env python3
        \"\"\"install_check.py – verify Python + tkinter before running Lazerem.\"\"\"

        import sys

        print(f"Python version : {sys.version}")

        if sys.version_info < (3, 9):
            print("FAIL: Python 3.9 or newer is required.")
            sys.exit(1)
        print("OK  : Python version is 3.9+")

        try:
            import tkinter  # noqa: F401
            print("OK  : tkinter is available")
        except ImportError:
            print("FAIL: tkinter is NOT available.")
            print()
            print("Install it with:")
            print("  Ubuntu/Debian : sudo apt install python3-tk")
            print("  Fedora        : sudo dnf install python3-tkinter")
            print("  Arch          : sudo pacman -S tk")
            print("  macOS brew    : brew install python-tk")
            print("  Windows       : Re-run the Python installer and enable")
            print("                  Optional Features > tcl/tk and IDLE")
            sys.exit(1)

        print()
        print("All checks passed – you can run Lazerem:")
        print("  python3 run_laser.py   (Linux / macOS)")
        print("  python  run_laser.py   (Windows)")
    """)
    (dest / "install_check.py").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a portable Lazerem USB bundle.")
    parser.add_argument(
        "--dest",
        default="dist/lazerem-portable",
        help="Output directory (default: dist/lazerem-portable)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.resolve()
    dest = Path(args.dest)
    if not dest.is_absolute():
        dest = repo_root / dest

    # Safety check – don't overwrite the source tree
    try:
        dest.relative_to(repo_root / "lazerem")
        print("ERROR: destination overlaps with the source package. Choose a different --dest.")
        sys.exit(1)
    except ValueError:
        pass

    if dest.exists():
        print(f"Removing existing bundle at {dest} …")
        shutil.rmtree(dest)

    dest.mkdir(parents=True)
    print(f"Creating portable bundle in {dest} …")

    # Copy entry point
    shutil.copy2(repo_root / "run_laser.py", dest / "run_laser.py")
    print("  copied run_laser.py")

    # Copy launchers
    for launcher in ("lazerem.sh", "lazerem.bat"):
        src = repo_root / launcher
        if src.exists():
            shutil.copy2(src, dest / launcher)
            print(f"  copied {launcher}")

    # Make shell launcher executable
    sh = dest / "lazerem.sh"
    if sh.exists():
        sh.chmod(sh.stat().st_mode | 0o111)

    # Copy package source
    copy_tree(repo_root / "lazerem", dest / "lazerem")
    print("  copied lazerem/ package")

    # Generate helper files
    make_readme(dest)
    print("  wrote  README.txt")

    make_install_check(dest)
    print("  wrote  install_check.py")

    # Summary
    total_files = sum(1 for _ in dest.rglob("*") if _.is_file())
    print()
    print(f"✓ Portable bundle ready: {dest}  ({total_files} files)")
    print()
    print("  Copy the entire folder to a USB drive.")
    print("  On the target machine:")
    print("    Windows   → double-click lazerem.bat")
    print("    Linux/mac → ./lazerem.sh  or  python3 run_laser.py")


if __name__ == "__main__":
    main()
