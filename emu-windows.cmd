@echo off
setlocal
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0emu_windows.py" %*
    exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0emu_windows.py" %*
    exit /b
)
echo Python 3.10 or newer is required for the source launcher.
echo Use the portable EmuWindows.exe distribution if Python is not installed.
pause
exit /b 1
