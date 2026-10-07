@echo off
title XemAi Mobile - Tailscale Setup
echo XemAi Mobile private phone access setup
echo.
where tailscale >nul 2>&1
if errorlevel 1 (
  echo Tailscale is not installed or not available in PATH.
  echo Install Tailscale on this PC and your Android phone first.
  pause
  exit /b 1
)
echo Configuring private HTTPS access to XemAi on port 8765...
tailscale serve --bg 8765
echo.
echo Current Tailscale Serve status:
tailscale serve status
echo.
echo Open the HTTPS URL shown above on your Android phone.
pause
