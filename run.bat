@echo off
title SlideCraft - PDF to PowerPoint Converter
cd /d "%~dp0"

echo ======================================================
echo           SlideCraft PDF to PowerPoint
echo ======================================================
echo.
echo Starting local server at http://127.0.0.1:8000 ...
echo The web browser will open automatically in a moment.
echo.
echo (Press Ctrl+C in this window at any time to stop the server)
echo.

:: Launch the browser in the background after a 2-second delay to let the server start
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

:: Start Uvicorn using the virtual environment if present, otherwise system python
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
) else (
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Server stopped with error code %ERRORLEVEL%.
    pause
)
