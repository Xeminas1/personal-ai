@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo Isolated Python 3.13 environment missing. Stop without training.
  pause
  exit /b 2
)
echo.
echo OPTIONAL: genuine two-step Qwen3.5 4B LoRA pilot with 16 fictional examples.
echo The pilot will use your RTX GPU and may consume substantial GPU memory.
echo It uses the already-downloaded PUBLIC 4B base model, with offline mode enabled.
echo It does NOT read personal chats, memories, GitHub comments, or logs.
echo It does NOT train or replace the XemAi 9B model or upload any weights.
echo It saves a separate private adapter only if gradients change actual LoRA weights.
echo.
set /p "CONFIRM=Type TRAIN to run the synthetic 4B experiment: "
if /I not "%CONFIRM%"=="TRAIN" (
  echo Cancelled. No training started.
  pause
  exit /b 0
)
"%PY%" -m training.synthetic_smoke --train --confirm "TRAIN SYNTHETIC 4B"
set "RESULT=%ERRORLEVEL%"
echo.
echo Qwen3.5 4B synthetic pilot finished with status %RESULT%.
pause
exit /b %RESULT%
