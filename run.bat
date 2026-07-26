@echo off
setlocal
cd /d "%~dp0"
title Palworld MS Toolkit

REM Pure batch/PowerShell bootstrap — works even if Python is not installed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo Launcher failed. See messages above.
  pause
)
exit /b %ERR%
