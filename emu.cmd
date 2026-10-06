@echo off
setlocal
where python >nul 2>&1
if not errorlevel 1 goto python
where py >nul 2>&1
if not errorlevel 1 goto launcher
echo Python 3.9 or newer is required. Install Python, then run this command again.
exit /b 1
:python
python "%~dp0emu" %*
exit /b
:launcher
py -3 "%~dp0emu" %*
exit /b
