@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)
echo [INFO] Python: %PY%

"%PY%" -c "import uiautomation, pywinauto, PIL, psutil" >nul 2>nul
if errorlevel 1 (
    echo [INFO] First run: installing dependencies: uiautomation pywinauto Pillow psutil
    "%PY%" -m pip install -r "%~dp0requirements.txt"
)

"%PY%" "%~dp0app.py"
echo.
echo Exit code: %errorlevel%
pause
