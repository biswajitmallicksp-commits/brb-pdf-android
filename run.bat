@echo off
REM ==========================================================================
REM  PDF Workbench - run from source (development)
REM  First run: creates .venv and installs packages (needs internet ONCE).
REM  Later runs: fully offline.
REM  You can pass PDF files:   run.bat "C:\path\file.pdf"
REM ==========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment in .venv ...
    py -3.12 -m venv .venv >nul 2>&1
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: Python was not found.
        echo Install Python 3.12 64-bit from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during installation.
        pause
        exit /b 1
    )
)

REM Install packages only when requirements.txt has changed since last time.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing packages ^(one time^) ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: package installation failed. Check the internet connection and try again.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

".venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo.
    echo The application ended with an error. See the log folder:
    echo %LOCALAPPDATA%\PDFWorkbench\logs
    pause
)
endlocal
