@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "AXIOM_VENV=%~dp0.venv"
set "AXIOM_VENV_PYTHON=%AXIOM_VENV%\Scripts\python.exe"

if not exist "%AXIOM_VENV_PYTHON%" (
	echo .venv Python not found: "%AXIOM_VENV_PYTHON%"
	echo Create or repair the virtual environment first, then rerun this launcher.
	pause
	exit /b 1
)

"%AXIOM_VENV_PYTHON%" src\main.py
pause

