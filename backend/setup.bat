@echo off
echo Setting up JARVIS AI Assistant...

echo.
echo [1/3] Creating Python Virtual Environment...
python -m venv venv
call venv\Scripts\activate.bat

echo.
echo [2/3] Installing Dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [3/3] Setting up environment variables...
if not exist .env (
    copy .env.example .env
    echo Please edit .env and add your Google and LiveKit API keys.
) else (
    echo .env already exists.
)

echo.
echo Setup Complete!
echo Run JARVIS using: venv\Scripts\activate.bat ^& python main.py
pause
