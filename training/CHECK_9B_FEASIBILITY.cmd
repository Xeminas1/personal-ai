@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Read-only hardware/planning report. Never connects to internet or loads a model.
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo The separate Python 3.13 training environment was not found.
  echo No changes made. Merge this script into the same training folder as before.
  pause
  exit /b 2
)
"%PY%" -m training.assess_9b --check
set "RESULT=%ERRORLEVEL%"
echo.
echo Qwen3.5 9B read-only feasibility check finished with status %RESULT%.
echo No model downloaded, trained, changed, installed or replaced.
pause
exit /b %RESULT%
