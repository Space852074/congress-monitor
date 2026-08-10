@echo off
setlocal EnableExtensions
C:\Windows\System32\chcp.com 65001 >nul 2>nul

cd /d "%~dp0" || goto fatal_cd

set "ROOT_DIR=%CD%"
set "PYTHON_CMD="
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

call :try_python_file "%ROOT_DIR%\.venv\Scripts\python.exe"
if defined PYTHON_CMD goto found_python

call :try_python_file "%ROOT_DIR%\venv\Scripts\python.exe"
if defined PYTHON_CMD goto found_python

call :try_python_cmd "py -3"
if defined PYTHON_CMD goto found_python

call :try_python_cmd "python"
if defined PYTHON_CMD goto found_python

echo No usable Python 3.9+ interpreter was found.
pause
exit /b 1

:found_python
echo ====================
echo Congress Monitor optimized runner
echo ====================
echo.
echo [Python]
echo %PYTHON_CMD%

if /I "%~1"=="--check" goto self_check

echo.
echo [Start]
%PYTHON_CMD% "%ROOT_DIR%\run_all.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ====================
if "%EXIT_CODE%"=="0" echo Finished. Press any key to exit.
if not "%EXIT_CODE%"=="0" echo Failed with exit code %EXIT_CODE%. Press any key to exit.
echo ====================
pause
exit /b %EXIT_CODE%

:self_check
echo Batch file parsed successfully. No scraper or Notion write was executed.
exit /b 0

:fatal_cd
echo Cannot enter script directory: %~dp0
pause
exit /b 1

:try_python_file
if defined PYTHON_CMD exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if "%ERRORLEVEL%"=="0" set "PYTHON_CMD="%~1""
exit /b 0

:try_python_cmd
if defined PYTHON_CMD exit /b 0
%~1 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if "%ERRORLEVEL%"=="0" set "PYTHON_CMD=%~1"
exit /b 0
