@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "AXIOM_VENV=%CD%\.venv"
set "AXIOM_VENV_PYTHON=%AXIOM_VENV%\Scripts\python.exe"
set "AXIOM_REQUIREMENTS=%CD%\requirements.txt"
set "AXIOM_BOOTSTRAP_DEPS="

if not exist "%AXIOM_VENV_PYTHON%" (
    echo Creating virtual environment in "%AXIOM_VENV%"...
    call :create_venv
    if errorlevel 1 (
        pause
        exit /b 1
    )
    set "AXIOM_BOOTSTRAP_DEPS=1"
)

if not exist "%AXIOM_VENV_PYTHON%" (
    echo Virtual environment Python not found: "%AXIOM_VENV_PYTHON%"
    pause
    exit /b 1
)

call :validate_venv
if errorlevel 1 (
    pause
    exit /b 1
)

call :ensure_pip
if errorlevel 1 (
    pause
    exit /b 1
)

if not exist "%AXIOM_REQUIREMENTS%" (
    echo requirements.txt not found: "%AXIOM_REQUIREMENTS%"
    pause
    exit /b 1
)

if defined AXIOM_BOOTSTRAP_DEPS (
    call :install_requirements
    if errorlevel 1 (
        pause
        exit /b 1
    )
) else (
    call :probe_dependencies
    if errorlevel 1 (
        echo Required packages are missing from the virtual environment. Installing requirements...
        call :install_requirements
        if errorlevel 1 (
            pause
            exit /b 1
        )
    )
)

call :check_torch_cuda
if errorlevel 1 (
    pause
    exit /b 1
)

"%AXIOM_VENV_PYTHON%" src\main.py
set "AXIOM_EXIT=%ERRORLEVEL%"
if not "%AXIOM_EXIT%"=="0" (
    echo Application exited with code %AXIOM_EXIT%.
)
pause
exit /b %AXIOM_EXIT%

:create_venv
where python >nul 2>&1
if not errorlevel 1 (
    python -m venv "%AXIOM_VENV%"
    if errorlevel 1 (
        echo Failed to create virtual environment at "%AXIOM_VENV%" with "python -m venv".
        exit /b 1
    )
    exit /b 0
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv "%AXIOM_VENV%"
    if errorlevel 1 (
        echo Failed to create virtual environment at "%AXIOM_VENV%" with "py -3 -m venv".
        exit /b 1
    )
    exit /b 0
)

echo No system Python interpreter was found.
echo Install a supported 64-bit Python first, ensure "python" or "py" is available, then rerun launch.bat.
exit /b 1

:validate_venv
"%AXIOM_VENV_PYTHON%" -V >nul 2>&1
if not errorlevel 1 (
    exit /b 0
)

echo The virtual environment at "%AXIOM_VENV%" is invalid or its base Python was removed.
echo Delete ".venv", install a supported system Python, and rerun launch.bat to recreate the environment.
exit /b 1

:ensure_pip
"%AXIOM_VENV_PYTHON%" -m pip --version >nul 2>&1
if not errorlevel 1 (
    exit /b 0
)

echo Bootstrapping pip in the virtual environment...
"%AXIOM_VENV_PYTHON%" -m ensurepip --upgrade >nul 2>&1
if errorlevel 1 (
    echo Failed to bootstrap pip inside "%AXIOM_VENV%".
    exit /b 1
)

"%AXIOM_VENV_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip is still unavailable after ensurepip.
    exit /b 1
)
exit /b 0

:probe_dependencies
"%AXIOM_VENV_PYTHON%" -c "import numpy, mss, ultralytics, PyQt6"
exit /b %ERRORLEVEL%

:install_requirements
echo Installing dependencies from requirements.txt...
"%AXIOM_VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip in "%AXIOM_VENV%".
    exit /b 1
)

"%AXIOM_VENV_PYTHON%" -m pip install -r "%AXIOM_REQUIREMENTS%"
if errorlevel 1 (
    echo Failed to install dependencies from "%AXIOM_REQUIREMENTS%".
    exit /b 1
)
exit /b 0

:check_torch_cuda
"%AXIOM_VENV_PYTHON%" -c "import torch, sys; sys.exit(0 if getattr(torch.version, 'cuda', None) and torch.cuda.is_available() else 1)" >nul 2>&1
if not errorlevel 1 (
    exit /b 0
)

echo PyTorch is missing or is not using a CUDA build in "%AXIOM_VENV%".
echo This project should not continue with a CPU-only torch install.
echo Run the following commands in the virtual environment, then rerun launch.bat:
echo   python -m pip install --upgrade pip
echo   python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
echo   python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available())"
exit /b 1

