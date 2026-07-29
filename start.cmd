@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 (
  echo.
  echo ThaiForge could not start. The error is shown above.
  pause
) else (
  echo.
  echo ThaiForge has stopped.
  pause
)
