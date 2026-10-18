@echo off
setlocal
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if errorlevel 1 (
    pause
    exit /b 1
)
echo [INFO] Python: %PY%

for %%i in ("%PY%..\..") do set "ENVROOT=%%~fi"
echo [INFO] Env root: %ENVROOT%

set "ADDBIN="
if exist "%ENVROOT%\Library\bin\" (
    set "ADDBIN=--add-binary=%ENVROOT%\Library\bin;."
)

"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    "%PY%" -m pip install pyinstaller
)

"%PY%" -m PyInstaller --noconfirm --clean --noconsole --onefile --icon "assets\icon.ico" %ADDBIN% --name "ElementCatcher" app.py
if errorlevel 1 (
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)
echo [INFO] Build OK: dist\ElementCatcher.exe
pause
