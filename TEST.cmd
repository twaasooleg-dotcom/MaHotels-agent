@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Virtual environment missing. Open START.cmd to install MaHotels.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -B -X utf8 -m unittest discover -s tests -v
if errorlevel 1 goto failed
"%~dp0.venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
echo Offline checks passed. No site or provider requests were made.
exit /b 0
:failed
echo Offline checks failed. Review the errors above.
exit /b 1
