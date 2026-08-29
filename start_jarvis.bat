@echo off
setlocal enabledelayedexpansion
title JARVIS Neural Assistant Launcher

:: Set UTF-8 Code Page & Python Environment
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Navigate to project root directory dynamically
cd /d "%~dp0"

echo =====================================================================
echo                    JARVIS AI ASSISTANT LAUNCHER                      
echo =====================================================================
echo [INFO] Project Root: %~dp0
echo.

:: Detect Virtual Environment
set VENV_PATH=%~dp0venv
if exist "%VENV_PATH%\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment (%VENV_PATH%)...
    call "%VENV_PATH%\Scripts\activate.bat"
) else (
    echo [WARNING] Virtual environment not found at %VENV_PATH%.
    echo [INFO] Falling back to system Python...
)

:: Set Python Path
set PYTHONPATH=%~dp0apps\backend;%PYTHONPATH%

echo.
echo [INFO] Launching JARVIS Unified Server...
echo   - Backend API: http://localhost:8000
echo   - Web Console: http://localhost:8000
echo   - LiveKit Agent: Activated
echo   - Dedicated Separate Browser: Auto-opening for all web processes
echo =====================================================================
echo.

start "JARVIS Unified Server" cmd /k "cd /d ""%~dp0apps\backend"" && set PYTHONUTF8=1 && set PYTHONPATH=%~dp0apps\backend && python main.py"

echo JARVIS has been launched in a dedicated terminal window.
echo You can keep this launcher window or close it at any time.
echo.
pause
