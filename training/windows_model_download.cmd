@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Offline-by-default owner-controlled public Qwen3.5 4B model download.
rem Nothing here trains, installs an Ollama model, or reads personal content.
set "MODEL=Qwen/Qwen3.5-4B"
set "REV=c7429d5a8ed57f4a9cfdaf1af76a8943eba0ae97"
set "BASE=%~dp0..\data\weight_training"
set "MODEL_DIR=%BASE%\models\%REV%"
set "HF=%BASE%\env_python313\Scripts\hf.exe"
set "PY=%BASE%\env_python313\Scripts\python.exe"

if /I "%~1"=="--check" goto CHECK
if /I "%~1"=="--download" goto DOWNLOAD
echo XemAi model download helper: NO action selected.
echo Read-only: windows_model_download.cmd --check
echo Optional, owner-approved model download: windows_model_download.cmd --download
exit /b 0

:CHECK
if not exist "%PY%" (
  echo Isolated Python 3.13 was not found. Run the training environment setup first.
  exit /b 2
)
if not exist "%HF%" (
  echo Hugging Face downloader was not found in the isolated environment.
  exit /b 2
)
if exist "%MODEL_DIR%\config.json" (
  echo A local model directory exists. This is NOT proof that all weight shards downloaded.
) else (
  echo No local Qwen3.5 4B checkpoint downloaded by this helper.
)
echo This check made no changes and used no network connection.
exit /b 0

:DOWNLOAD
call "%~f0" --check
if errorlevel 1 exit /b 2
echo.
echo Optional download of PUBLIC official Qwen3.5 4B BF16 model weights.
echo Source: https://huggingface.co/Qwen/Qwen3.5-4B
echo License: Apache-2.0
echo Revision: %REV%
echo Size: approximately 9.34 GB; network and storage required.
echo Destination: separate data/weight_training/models directory.
echo No private chats, bridge messages, memory, logs or tokens are used.
echo No model deployment, training, configuration changes, or Ollama replacement.
echo.
set /p "CONFIRM=Type DOWNLOAD to approve downloading the public model: "
if not "%CONFIRM%"=="DOWNLOAD" (
  echo Cancelled; no model download started.
  exit /b 0
)
set "HF_HUB_DISABLE_IMPLICIT_TOKEN=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
if errorlevel 1 (
  echo Could not create local model directory.
  exit /b 2
)
"%HF%" download %MODEL% --revision %REV% --local-dir "%MODEL_DIR%"
if errorlevel 1 (
  echo The model download was interrupted or failed. This is NOT a complete checkpoint.
  echo Rerunning the same command can resume verified public files.
  exit /b 2
)
"%PY%" -c "import json,sys; from pathlib import Path; p=Path(sys.argv[1]); d=json.loads((p/'config.json').read_text('utf-8')); s=[p/'model.safetensors-00001-of-00002.safetensors',p/'model.safetensors-00002-of-00002.safetensors']; assert d.get('model_type')=='qwen3_5' and d.get('text_config',{}).get('hidden_size')==2560; assert (p/'tokenizer_config.json').is_file() and (p/'model.safetensors.index.json').is_file(); assert all(f.is_file() and f.stat().st_size>1000000000 for f in s); print('Official 4B model files and architecture detected; no training performed.')" "%MODEL_DIR%"
if errorlevel 1 (
  echo Local checkpoint validation failed; do not start training.
  exit /b 2
)
echo.
echo A pinned public 4B checkpoint is present for a SEPARATE training pilot.
echo Your active XemAi Qwen 9B model has not been changed.
exit /b 0
