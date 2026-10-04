@echo off
rem ------------------------------------------------------------------
rem  BRB PDF for Android - copy the OCR language files into the project
rem  (English, Bengali, Hindi). Run this ONCE before building the app.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "DEST=%~dp0app\src\main\assets\tessdata"
if not exist "%DEST%" mkdir "%DEST%"

set "SRC="
for %%P in (
  "%USERPROFILE%\Desktop\PDFWorkbench\tessdata"
  "%USERPROFILE%\OneDrive\Desktop\PDFWorkbench\tessdata"
  "%USERPROFILE%\Desktop\PDFWorkbench\dist\PDFWorkbench\tessdata"
  "%USERPROFILE%\OneDrive\Desktop\PDFWorkbench\dist\PDFWorkbench\tessdata"
  "%USERPROFILE%\Desktop\tessdata"
  "%~dp0tessdata"
) do (
  if not defined SRC if exist "%%~P\eng.traineddata" set "SRC=%%~P"
)

if not defined SRC (
  echo Could not find the OCR language files automatically.
  echo They are in the "tessdata" folder of the Windows PDFWorkbench program
  echo ^(the folder that contains eng.traineddata^).
  echo.
  set /p "SRC=Drag that tessdata folder into this window and press Enter: "
)
set "SRC=%SRC:"=%"

if not exist "%SRC%\eng.traineddata" (
  echo.
  echo ERROR: eng.traineddata was not found in "%SRC%".
  pause
  exit /b 1
)

echo Copying from "%SRC%" ...
for %%L in (eng ben hin) do (
  if exist "%SRC%\%%L.traineddata" (
    copy /y "%SRC%\%%L.traineddata" "%DEST%\" >nul && echo   %%L.traineddata  OK
  ) else (
    echo   %%L.traineddata  MISSING - this language will not be available
  )
)
echo.
echo Done. Now open this folder in Android Studio and press Run.
pause
