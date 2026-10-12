@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem XemAi optional local training environment - NEVER a model trainer or updater.
rem Dry-run by default; --install must be explicitly selected by the owner.
set "ENV_DIR=%~dp0..\data\weight_training\env_python313"
set "ENV_PY=%ENV_DIR%\Scripts\python.exe"

if /I "%~1"=="--check" goto CHECK
if /I "%~1"=="--install" goto INSTALL
echo XemAi training environment helper (Windows).
echo No changes have been made.
echo.
echo Read-only check:  windows_setup.cmd --check
echo Owner-approved local package setup:  windows_setup.cmd --install
echo This helper never reads private chats, imports bridge records,
echo downloads models, runs training, uploads data or switches Ollama models.
exit /b 0

:CHECK
echo XemAi training environment check (read-only).
where uv >nul 2>nul
if errorlevel 1 (echo uv: not installed) else (echo uv: available)
if exist "%ENV_PY%" (
  echo Isolated Python: exists
  "%ENV_PY%" --version
  "%ENV_PY%" -c "import importlib.metadata as m; names=('torch','transformers','trl','unsloth','datasets','peft'); print('Packages:', ' '.join(n+'='+((m.version(n)) if any(d.metadata['Name'].lower()==n for d in m.distributions()) else 'missing') for n in names))"
) else (
  echo Isolated Python: not installed
)
echo No installation, training or model changes performed.
exit /b 0

:INSTALL
echo.
echo This OPTIONAL command installs a separate Python 3.13 environment
echo and CUDA training libraries into a separate local data folder.
echo It may download multiple gigabytes of packages from package services.
echo It will NOT download model weights, alter the live Ollama model,
echo touch XemAi memory, bridge, pairing, chats or deploy anything.
echo.
set /p "CONFIRM=Type INSTALL to allow downloading dependencies: "
if /I not "%CONFIRM%"=="INSTALL" (
  echo Cancelled: no changes made.
  exit /b 0
)
where uv >nul 2>nul
if errorlevel 1 (
  echo.
  echo uv package installer was not found.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo winget is unavailable. Install uv from its official instructions:
    echo https://docs.astral.sh/uv/getting-started/installation/
    exit /b 2
  )
  echo Installing the official Astral uv package using winget.
  echo You may be asked to accept the Microsoft package install.
  winget install -e --id astral-sh.uv --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo uv installer failed; no training attempted.
    exit /b 2
  )
  echo uv installed. Close this window and run the command again so PATH refreshes.
  exit /b 0
)
if exist "%ENV_DIR%" (
  echo Environment folder already exists. Refusing to overwrite it.
  echo Use --check to inspect or review it manually.
  exit /b 2
)
echo Installing standalone Python 3.13 without replacing Python 3.14...
uv python install 3.13
if errorlevel 1 exit /b 2
echo Creating private, isolated training environment...
if not exist "%~dp0..\data\weight_training" mkdir "%~dp0..\data\weight_training"
if errorlevel 1 exit /b 2
uv venv "%ENV_DIR%" --python 3.13
if errorlevel 1 exit /b 2
if not exist "%ENV_PY%" (
  echo Environment interpreter was not created; no training attempted.
  exit /b 2
)
echo Installing official Unsloth training dependencies and compatible CUDA backend...
uv pip install --python "%ENV_PY%" unsloth --torch-backend=auto
if errorlevel 1 (
  echo Package setup did not complete. No model was trained.
  exit /b 2
)
echo.
echo Checking CUDA BF16 and Unsloth library imports...
"%ENV_PY%" -c "import unsloth, torch, transformers; print('CUDA available:',torch.cuda.is_available()); print('BF16 available:', torch.cuda.is_available() and torch.cuda.is_bf16_supported()); print('Transformers:', transformers.__version__); assert int(transformers.__version__.split('.')[0]) >= 5; assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()"
if errorlevel 1 (
  echo Dependencies installed, but CUDA/Unsloth verification FAILED.
  echo Do not train until the GPU environment has been reviewed.
  exit /b 2
)
echo.
echo Training environment ready for a separately approved pilot.
echo No model, adapter, training dataset or Ollama configuration was changed.
exit /b 0
