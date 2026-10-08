@echo off
cd /d "%~dp0"
echo Restarting XemAi mobile server...
python -c "from app.mobile_runtime import restart_mobile_server_process; import sys; sys.exit(0 if restart_mobile_server_process() else 1)"
if errorlevel 1 (
  echo Failed to restart the XemAi mobile server.
) else (
  echo XemAi mobile server is now running the current version.
)
pause
