@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo Isolated Python 3.13 environment missing. No training started.
  pause
  exit /b 2
)
echo.
echo Qwen3.5 4B DIAGNOSTIC compatibility run on fictional examples only.
echo The previous RTX 5080 run reached 0/2 and exited with RuntimeError.
echo This trial disables ONLY the Unsloth auto-compiler (supported debug switch).
echo It does not install causal-conv1d, modify Ollama, change the 9B model,
echo access any private conversation, or upload model/data.
echo You can cancel now without starting any training.
echo The run could still be slow or fail. If so, share only DIAGNOSTIC lines.
echo.
set /p "CONFIRM=Type DIAGNOSE to allow a two-step GPU training retry: "
if not "%CONFIRM%"=="DIAGNOSE" (
  echo Cancelled; no GPU training started.
  pause
  exit /b 0
)
"%PY%" -m training.synthetic_smoke --train --compat-no-compile --confirm "TRAIN SYNTHETIC 4B"
set "RESULT=%ERRORLEVEL%"
echo.
echo Compatibility training ended with status %RESULT%.
echo A saved adapter is NOT confirmed unless the run reports explicit changes and saved manifest.
pause
exit /b %RESULT%
