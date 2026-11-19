@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CHANGE-MAHOTELS-API-KEYS.ps1"
set "keyEditorResult=%errorlevel%"
pause
exit /b %keyEditorResult%
