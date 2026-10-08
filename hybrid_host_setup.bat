@echo off
setlocal
title XemAi Hybrid Host Pairing
cd /d "%~dp0"
python hybrid_setup.py host
echo.
pause
