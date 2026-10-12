@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo Isolated Python 3.13 environment missing. Merge this ZIP into your earlier training setup folder.
  pause
  exit /b 2
)
"%PY%" -m training.synthetic_smoke --check
set "RESULT=%ERRORLEVEL%"
echo.
echo Local pilot check finished with status %RESULT%.
pause
exit /b %RESULT%
