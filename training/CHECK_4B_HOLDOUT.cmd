@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo Isolated training environment missing. Nothing has changed.
  pause
  exit /b 2
)
echo Checking pinned Qwen3.5 4B model and locally saved adapter manifest, without GPU loading.
"%PY%" -m training.evaluate_synthetic_adapter --check
set "RESULT=%ERRORLEVEL%"
echo.
echo Read-only holdout preflight ended with status %RESULT%.
pause
exit /b %RESULT%
