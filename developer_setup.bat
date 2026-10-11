@echo off
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 developer_setup.py
) else (
  python developer_setup.py
)
echo.
pause
