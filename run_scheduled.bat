@echo off
setlocal EnableExtensions

cd /d "%~dp0" || exit /b 1
if not exist "logs" mkdir "logs"

echo.>> "logs\scheduled_run.log"
echo ==================================================>> "logs\scheduled_run.log"
echo [%DATE% %TIME%] Scheduled run started>> "logs\scheduled_run.log"

call "%~dp0run_all.bat" --scheduled >> "logs\scheduled_run.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

echo [%DATE% %TIME%] Scheduled run finished with exit code %EXIT_CODE%>> "logs\scheduled_run.log"
exit /b %EXIT_CODE%
