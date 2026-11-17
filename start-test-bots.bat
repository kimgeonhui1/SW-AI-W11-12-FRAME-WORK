@echo off
rem TEST ONLY: add 1-3 test bots to a room (asks room code, bot count, mode, seed).
rem Double-click. Runs tools\windows\start-test-bots.ps1 with Windows PowerShell 5.1.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\start-test-bots.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
