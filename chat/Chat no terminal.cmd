@echo off
cd /d "%~dp0.."
title Chat de suporte
chcp 65001 >nul
set PYTHONDONTWRITEBYTECODE=1
"%~dp0..\.venv\Scripts\python.exe" "%~dp0chat_terminal.py"
pause
