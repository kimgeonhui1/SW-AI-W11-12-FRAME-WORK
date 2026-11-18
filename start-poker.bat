@echo off
rem Start JUNGLE POKER LAB servers: DBMS -> Redis -> Poker API -> web (no test bots).
rem Double-click. Runs tools\windows\start-poker.ps1 with Windows PowerShell 5.1.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\start-poker.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
