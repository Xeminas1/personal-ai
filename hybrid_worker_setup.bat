@echo off
setlocal
title XemAi Hybrid Worker Setup
cd /d "%~dp0"
set "XEMAI_SETUP_MODE=%~1"

powershell -NoProfile -Command "$p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent(); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
  if /i "%XEMAI_SETUP_MODE%"=="--silent" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '--silent' -Verb RunAs"
  ) else (
    echo XemAi needs an Administrator window once so Tailscale Serve can be configured.
    echo Requesting permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  )
  exit /b
)

if /i "%XEMAI_SETUP_MODE%"=="--silent" (
  if not exist "%~dp0logs" mkdir "%~dp0logs"
  python hybrid_setup.py worker --silent > "%~dp0logs\hybrid_autosetup.log" 2>&1
  exit /b %ERRORLEVEL%
)

python hybrid_setup.py worker
echo.
pause
