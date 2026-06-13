@echo off
echo Starting Jarvis Assistant...

:: Change directory to the script's location (Jarvis root)
cd /d "%~dp0"

:: Activate the virtual environment
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else if exist backend\venv\Scripts\activate.bat (
    call backend\venv\Scripts\activate.bat
) else (
    echo [WARNING] Virtual environment not found. Jarvis might fail to start if dependencies are not installed globally.
)

:: Navigate to backend and start the server in a new window
cd backend
echo Launching backend server...
start "Jarvis Server" cmd /k "title Jarvis Server && python main.py console"

echo Done! The backend is running in a new window.
timeout /t 3 > nul
