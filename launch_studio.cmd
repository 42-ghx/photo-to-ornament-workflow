@echo off
setlocal
cd /d "%~dp0"
if defined ORNAMENT_PYTHON (
  "%ORNAMENT_PYTHON%" "%~dp0setup\start_studio.py" %*
  goto finished
)
python3.12 -c "import sys; raise SystemExit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
  python3.12 "%~dp0setup\start_studio.py" %*
  goto finished
)
py -3 -c "import sys; raise SystemExit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0setup\start_studio.py" %*
  goto finished
)
python -c "import sys; raise SystemExit(sys.version_info < (3,11))" >nul 2>&1
if not errorlevel 1 (
  python "%~dp0setup\start_studio.py" %*
  goto finished
)
echo Python 3.11+ was not found. Install Python 3.12 from python.org with PATH enabled.
echo Or set ORNAMENT_PYTHON to an existing python.exe and run this file again.
pause
exit /b 1
:finished
if errorlevel 1 (
  echo Studio startup failed. See the message above.
  pause
  exit /b 1
)
exit /b 0
