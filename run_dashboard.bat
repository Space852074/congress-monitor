@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "dashboard\app.py" serve --host 127.0.0.1 --port 8765
  goto :eof
)

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" "dashboard\app.py" serve --host 127.0.0.1 --port 8765
  goto :eof
)

if exist "C:\AIV~1\RVC-beta\runtime\python.exe" (
  "C:\AIV~1\RVC-beta\runtime\python.exe" "dashboard\app.py" serve --host 127.0.0.1 --port 8765
  goto :eof
)

python "dashboard\app.py" serve --host 127.0.0.1 --port 8765
