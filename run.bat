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
    "%PY%" -c "import uiautomation, pywinauto, PIL, psutil" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. Check your network, or run manually:
        echo   "%PY%" -m pip install -r "%~dp0requirements.txt"
        pause
        exit /b 1
    )
)

if "%PYW%"=="%PY%" (
    echo [WARN] pythonw.exe not found, running with a console window.
)
start "" "%PYW%" "%~dp0app.py"
