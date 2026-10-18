@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)
echo [INFO] Python: %PY%
"%PY%" -m pip install -r "%~dp0requirements.txt"
echo.
pause
