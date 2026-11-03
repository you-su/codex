@echo off
setlocal
cd /d "%~dp0"
if not exist "server.py" goto incomplete
if not exist "index.html" goto incomplete
if not exist "logo.svg" goto incomplete
if exist "runtime\python.exe" (
  "runtime\python.exe" -u "server.py"
  goto finished
)
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 (
  py -3 -u "server.py"
  goto finished
)
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 (
  python -u "server.py"
  goto finished
)
echo Python 3.10+ is required. Install Python from python.org and enable Add to PATH.
echo Do not run start.bat directly inside the ZIP.
goto finished
:incomplete
echo Missing project files. Extract the COMPLETE ZIP to a writable folder first.
:finished
echo.
echo If the server is running but no page opened, visit http://127.0.0.1:8765
echo For startup errors, send a screenshot of this window.
pause
