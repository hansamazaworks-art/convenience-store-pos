@echo off
rem Builds the Windows programs into dist\ConvenienceStorePOS (takes a few minutes).
rem Run in Command Prompt from the project folder:  build_exe.bat
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The .venv folder is missing. See docs\SETUP.md, Step 3.
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean pos.spec || exit /b 1
copy /y ".env.example" "dist\ConvenienceStorePOS\.env.example" >nul
copy /y "docs\SETUP.md" "dist\ConvenienceStorePOS\SETUP.md" >nul
if exist "MANUAL.md" copy /y "MANUAL.md" "dist\ConvenienceStorePOS\MANUAL.md" >nul
echo.
echo Done: dist\ConvenienceStorePOS\ConvenienceStorePOS.exe and "POS Tools.exe"
echo Copy the whole dist\ConvenienceStorePOS folder to the store PC.
