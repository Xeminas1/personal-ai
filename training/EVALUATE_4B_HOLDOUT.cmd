@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
set "PY=%CD%\data\weight_training\env_python313\Scripts\python.exe"
if not exist "%PY%" (
  echo Isolated training environment missing. Nothing has changed.
  pause
  exit /b 2
)
echo.
echo OPTIONAL held-out evaluation of your existing SYNTHETIC Qwen3.5 4B adapter.
echo The original 4B base and adapter are compared on four reserved fictional examples.
echo It loads your RTX GPU model read-only, computes losses, and prints numbers.
echo It cannot retrain, merge, replace or deploy your XemAi Qwen3.5 9B model.
echo It does not read chat history or access GitHub bridge. No network or new packages.
echo The tiny four-example test DOES NOT prove better conversations or intelligence.
echo Run CHECK_4B_HOLDOUT first. You may cancel without modifying anything.
echo.
set /p "CONFIRM=Type EVALUATE to approve this GPU-only local comparison: "
if not "%CONFIRM%"=="EVALUATE" (
  echo Cancelled; no GPU evaluation started.
  pause
  exit /b 0
)
"%PY%" -m training.evaluate_synthetic_adapter --evaluate --confirm "EVALUATE SYNTHETIC 4B"
set "RESULT=%ERRORLEVEL%"
echo.
echo Local read-only 4B holdout evaluation finished with status %RESULT%.
echo The results indicate ONLY a four-example synthetic answer-loss comparison.
pause
exit /b %RESULT%
