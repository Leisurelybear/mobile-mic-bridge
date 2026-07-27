@echo off
setlocal
cd /d "%~dp0"

REM Double-click friendly launcher for Mobile Mic Bridge receiver GUI.
REM Pass extra args through, e.g. start-receiver.bat -Cli -- --token secret

where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-receiver.ps1" %*
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-receiver.ps1" %*
exit /b %ERRORLEVEL%
