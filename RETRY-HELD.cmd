@echo off
cd /d "%~dp0"
echo Retry inspected held jobs. All article and image quality gates still apply.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" retry-held
if errorlevel 1 goto done
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" run
:done
pause
