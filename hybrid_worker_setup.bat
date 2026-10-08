@echo off
setlocal
title XemAi Hybrid Worker Setup
cd /d "%~dp0"

powershell -NoProfile -Command "$p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent(); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
  echo XemAi needs an Administrator window once so Tailscale Serve can be configured.
  echo Requesting permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

python hybrid_setup.py worker
echo.
pause
