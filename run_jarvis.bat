@echo off
echo Starting JARVIS Backend...
cd /d "%~dp0backend"
call venv\Scripts\activate.bat

:: Start the Python backend (this will block until closed)
python main.py
