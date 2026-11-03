@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist "runtime\pythonw.exe" goto missing
"runtime\python.exe" -X utf8 -c "from PySide6.QtWidgets import QApplication" >nul 2>&1
if errorlevel 1 goto missing
start "" "runtime\pythonw.exe" -X utf8 "%~dp0desktop_pet.py"
popd
exit /b 0
:missing
echo Download and fully extract the latest fish-api-pro-windows-x64.zip from Releases.
echo This desktop pet requires the included Python and Qt runtime.
pause
popd
exit /b 1
