@echo off  
chcp 65001 >nul  
setlocal  
cd /d "%~dp0"  
if exist ".venv\Scripts\python.exe" (  
    ".venv\Scripts\python.exe" congress_terminal.py shell  
) else if exist "venv\Scripts\python.exe" (  
    "venv\Scripts\python.exe" congress_terminal.py shell  
) else (  
    python congress_terminal.py shell  
)  
pause 
