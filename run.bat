@echo off
setlocal
cd /d "%~dp0"

REM System Python for GUI (needs tkinter). PlM edits use Downloads\python312 worker.
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found on PATH.
  pause
  exit /b 1
)

python -c "import customtkinter" 1>nul 2>nul
if errorlevel 1 (
  echo Installing customtkinter...
  python -m pip install customtkinter --quiet
)
python -c "import palworld_save_tools" 1>nul 2>nul
if errorlevel 1 (
  echo Installing palworld-save-tools...
  python -m pip install palworld-save-tools --quiet
)

echo Starting Palworld MS Toolkit...
python "%~dp0app.py"
if errorlevel 1 pause
