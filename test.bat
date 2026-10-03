@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Run run.bat once first to create the environment.
  pause
  goto :eof
)
set PYTHONIOENCODING=utf-8
echo ===== 1) Automated tests (pytest) =====
".venv\Scripts\python.exe" -m pytest -q
echo.
echo ===== 2) Agent health check (every agent's self-test) =====
".venv\Scripts\python.exe" -m mihwar.healthcheck
echo.
echo ===== 3) UI smoke test (every page, every role, headless Edge) =====
".venv\Scripts\python.exe" scripts\smoke_ui.py
pause
