@echo off
REM ==========================================================================
REM  PDF Workbench - build the Windows program
REM  Result: dist\PDFWorkbench\PDFWorkbench.exe  (copy the whole folder anywhere)
REM ==========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment in .venv ...
    py -3.12 -m venv .venv >nul 2>&1
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo ERROR: Python was not found. Install Python 3.12 64-bit and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

echo [1/4] Installing build packages ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
copy /y requirements.txt ".venv\requirements.installed" >nul

echo [2/4] Running tests ...
".venv\Scripts\python.exe" -m unittest discover -s tests
if errorlevel 1 (
    echo Tests failed - the build was stopped so a broken program is not produced.
    goto :fail
)

echo [3/4] Building the program ...
if exist build rmdir /s /q build
if exist dist\PDFWorkbench rmdir /s /q dist\PDFWorkbench
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
    --name PDFWorkbench ^
    --icon assets\app.ico ^
    --add-data "assets;assets" ^
    --exclude-module tkinter ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtMultimedia ^
    main.py
if errorlevel 1 goto :fail

echo [4/4] Copying OCR language files and documentation ...
if not exist tessdata\eng.traineddata (
    echo ERROR: tessdata\eng.traineddata is missing - OCR would not work.
    goto :fail
)
xcopy /e /i /y /q tessdata dist\PDFWorkbench\tessdata >nul
copy /y README.md dist\PDFWorkbench\ >nul
copy /y THIRD_PARTY_LICENSES.md dist\PDFWorkbench\ >nul

echo.
echo ==========================================================================
echo  Done.  Program:  %CD%\dist\PDFWorkbench\PDFWorkbench.exe
echo  Copy the whole dist\PDFWorkbench folder to wherever you want to keep it.
echo ==========================================================================
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Scroll up to see the first error message.
pause
exit /b 1
