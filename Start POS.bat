@echo off
rem Double-click to start the POS (MySQL must be running in XAMPP).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo The .venv folder is missing. See docs\SETUP.md, Step 3.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
