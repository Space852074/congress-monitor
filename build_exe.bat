@echo off
setlocal EnableExtensions
C:\Windows\System32\chcp.com 65001 >nul 2>nul

cd /d "%~dp0" || exit /b 1

set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0..\active_files\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Python runtime was not found.
  pause
  exit /b 1
)

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name CongressMonitor ^
  --collect-submodules committees ^
  --collect-submodules core ^
  run_all.py

if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Created: %CD%\dist\CongressMonitor.exe
pause
