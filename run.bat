@echo off
cd /d "%~dp0"
start "" "%~dp0XemAiServer.pyw"
timeout /t 1 /nobreak >nul
start "" "%~dp0XemAi.pyw"
exit /b
