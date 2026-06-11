@echo off
echo ==========================================
echo   Jarvis Windows Startup Installer
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\Jarvis Startup.lnk"
set "TARGET_PATH=%SCRIPT_DIR%jarvis_startup.bat"

echo Creating shortcut in Windows Startup folder...
echo Destination: %STARTUP_FOLDER%
echo.

powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut('%SHORTCUT_PATH%'); $shortcut.TargetPath = '%TARGET_PATH%'; $shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $shortcut.Description = 'Starts Jarvis Assistant'; $shortcut.Save()"

if exist "%SHORTCUT_PATH%" (
    echo [SUCCESS] Shortcut created!
    echo Jarvis will now start automatically whenever you log into Windows.
) else (
    echo [ERROR] Failed to create shortcut.
)

echo.
pause
