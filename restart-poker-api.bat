@echo off
rem Restart only the Poker API that start-poker.bat started.
rem Double-click. Runs tools\windows\restart-poker-api.ps1 with Windows PowerShell 5.1.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\restart-poker-api.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
