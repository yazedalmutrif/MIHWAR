@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title Mihwar

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\Scripts\python.exe" (
  echo [Mihwar] Creating the virtual environment...
  %PY% -m venv .venv || goto :nopython
)

echo [Mihwar] Checking requirements (the first run needs internet and takes about a minute)...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :piperr

if "%MIHWAR_PORT%"=="" set "MIHWAR_PORT=8090"
echo [Mihwar] Starting on http://127.0.0.1:%MIHWAR_PORT%/  (close this window to stop)
if "%MIHWAR_NO_BROWSER%"=="" start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%MIHWAR_PORT%/"
".venv\Scripts\python.exe" -m mihwar
goto :eof

:nopython
echo.
echo Python 3.10 or newer is required: https://www.python.org/downloads/
echo During setup, tick "Add python.exe to PATH", then run this file again.
pause
goto :eof

:piperr
echo.
echo Could not install the requirements. Check the internet connection and run this file again.
pause
