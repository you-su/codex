@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto location_error
if not exist "server.py" goto incomplete
if not exist "index.html" goto incomplete
if not exist "logo.svg" goto incomplete
if exist "runtime\python.exe" goto portable
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto launcher
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto installed
echo Python runtime is missing. Download fish-api-pro-windows-x64.zip from Releases.
echo The GitHub Source code ZIP does not include the runtime.
goto failed
:portable
"runtime\python.exe" -X utf8 -u "server.py"
goto result
:launcher
py -3 -X utf8 -u "server.py"
goto result
:installed
python -X utf8 -u "server.py"
:result
if errorlevel 1 goto failed
popd
exit /b 0
:incomplete
echo Required files are missing. Extract ALL files before running start.bat.
:failed
echo.
echo Startup failed. Keep this window open and send its error message.
pause
popd
exit /b 1
:location_error
echo Cannot access the application folder. Extract the ZIP to a local writable folder.
pause
exit /b 1
