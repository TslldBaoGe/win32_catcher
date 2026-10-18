@echo off
REM ============================================================
REM  Auto-detect a usable Python interpreter (by priority).
REM  Result:  PY  = console python.exe (dep check / install)
REM           PYW = pythonw.exe (no console; fallback = PY)
REM  Override: set env var PYTHON_EXE to a full python.exe path
REM ============================================================
set "PY="
set "PYW="
pushd "%~dp0"

if defined PYTHON_EXE if exist "%PYTHON_EXE%" (
    set "PY=%PYTHON_EXE%"
    goto :resolved
)

if exist "runtime\pythonw.exe" (
    set "PY=runtime\python.exe"
    set "PYW=runtime\pythonw.exe"
    goto :resolved
)
if exist "runtime\python.exe" (
    set "PY=runtime\python.exe"
    goto :resolved
)

REM ---- build candidate list ----
set "CAND=%TEMP%\element_catcher_python.txt"
py -3 -c "import sys;print(sys.executable)" >"%CAND%" 2>nul
where python.exe 2>nul | findstr /i /v "WindowsApps" >>"%CAND%" 2>nul
(for %%d in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%USERPROFILE%\Miniconda3" "%USERPROFILE%\Anaconda3") do (
    if exist "%%~d\python.exe" echo %%~d\python.exe
)) >>"%CAND%" 2>nul

REM ---- prefer interpreter saved by this app (data/python_path.txt) ----
set "SETVAL="
if exist "data\python_path.txt" (
    for /f "usebackq delims=" %%i in (`type "data\python_path.txt"`) do set "SETVAL=%%i"
)
if defined SETVAL if exist "%SETVAL%" (
    set "PY=%SETVAL%"
    goto :pop
)
findstr /r /v "^$" "%CAND%" 2>nul | findstr /i /v "WindowsApps" >"%CAND%.tmp" 2>nul
move /y "%CAND%.tmp" "%CAND%" >nul 2>nul

REM ---- prefer one that already has the dependencies ----
for /f "usebackq delims=" %%i in ("%CAND%") do (
    if not defined PY (
        "%%i" -c "import uiautomation, pywinauto, PIL, psutil" >nul 2>nul && set "PY=%%i"
    )
)

REM ---- none has deps: use first candidate (run.bat will install) ----
if not defined PY (
    for /f "usebackq delims=" %%i in ("%CAND%") do (
        if not defined PY set "PY=%%i"
    )
)
if exist "%CAND%" del "%CAND%" >nul 2>nul

if not defined PY (
    echo [ERROR] Python not found. Pick one:
    echo   1. Install Python 3.10+ from python.org
    echo      ^(check "Add Python to PATH" and the py launcher^)
    echo   2. Set env var PYTHON_EXE to a full python.exe path
    echo   3. Unzip a portable Python into the runtime\ folder
    popd
    exit /b 1
)

:pop
popd
:resolved
for %%i in ("%PY%") do set "PYDIR=%%~dpi"
if exist "%PYDIR%pythonw.exe" (
    set "PYW=%PYDIR%pythonw.exe"
) else (
    set "PYW=%PY%"
)
exit /b 0
