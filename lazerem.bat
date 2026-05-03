@echo off
REM lazerem.bat – Windows launcher for Lazerem (Ray5W Laser Control)
REM Works from any directory, including a USB drive.
REM
REM Double-click this file, or run it from a Command Prompt.

cd /d "%~dp0"

REM ── Locate Python ────────────────────────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo ====================================================================
    echo   ERROR: Python was not found on this system.
    echo ====================================================================
    echo.
    echo   Download and install Python 3.9+ from:
    echo     https://www.python.org/downloads/
    echo.
    echo   During installation:
    echo     ^* Check  "Add Python to PATH"      ^(on the first screen^)
    echo     ^* Expand "Optional Features" and enable "tcl/tk and IDLE"
    echo       ^(this installs tkinter, which Lazerem requires^)
    echo.
    echo   After installing, run this file again.
    echo.
    pause
    exit /b 1
)

REM ── Check Python version ─────────────────────────────────────────────────
for /f "tokens=*" %%v in ('python -c "import sys; print(sys.version_info.major)"') do set PY_MAJOR=%%v
if "%PY_MAJOR%" neq "3" (
    echo.
    echo ERROR: Python 3 is required ^(found Python %PY_MAJOR%^).
    echo        Download Python 3.9+ from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM ── Check tkinter ────────────────────────────────────────────────────────
python -c "import tkinter" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo ====================================================================
    echo   ERROR: tkinter is not available in your Python installation.
    echo ====================================================================
    echo.
    echo   Re-run the Python installer and enable "tcl/tk and IDLE" under
    echo   "Optional Features", then try again.
    echo.
    echo   Alternatively, install python-tk via winget:
    echo     winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

REM ── Launch Lazerem ───────────────────────────────────────────────────────
python run_laser.py %*
if %ERRORLEVEL% neq 0 pause
