@echo off
REM Fitbit API Startup Script for Windows
REM This script sets up the environment and starts the Flask application

setlocal enabledelayedexpansion

echo ============================================================
echo Fitbit Single-User Data Ingestion App
echo Startup Script
echo ============================================================
echo.

REM Check Python version
echo Checking Python version...
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python 3.12 or later.
    pause
    exit /b 1
)

python --version
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo Virtual environment not found. Creating one...
    python -m venv venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Upgrade pip
echo Upgrading pip...
python -m pip install --quiet --upgrade pip

REM Install/update dependencies
echo Installing dependencies...
pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies.
    pause
    exit /b 1
)
echo Dependencies installed.
echo.

REM Check for .env file and load variables
if exist ".env" (
    echo Found .env file, loading variables...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            set "%%a=%%b"
        )
    )
)

REM Check for required environment variables
echo Checking environment variables...
set MISSING_VARS=0

if "%FITBIT_CLIENT_ID%"=="" (
    echo Error: FITBIT_CLIENT_ID is not set.
    set MISSING_VARS=1
)

if "%FITBIT_CLIENT_SECRET%"=="" (
    echo Error: FITBIT_CLIENT_SECRET is not set.
    set MISSING_VARS=1
)

if %MISSING_VARS%==1 (
    echo.
    echo Please set these variables:
    echo   1. Create a .env file (see env-example.txt), or
    echo   2. Set them in your environment:
    echo.
    echo      set FITBIT_CLIENT_ID=your_client_id_here
    echo      set FITBIT_CLIENT_SECRET=your_client_secret_here
    echo.
    echo See README.md or QUICKSTART.md for detailed instructions.
    pause
    exit /b 1
)

echo Required environment variables are set.
echo.

REM Set default Flask secret key if not set
if "%FLASK_SECRET_KEY%"=="" (
    echo Warning: FLASK_SECRET_KEY not set, using default (not recommended for production).
    echo.
)

REM Check if database directory needs to be created
if not exist "fitbit_data" (
    echo Creating fitbit_data directory...
    mkdir fitbit_data\default
    echo Data directory created.
    echo.
)

REM Display configuration summary
echo ============================================================
echo Configuration Summary:
echo   Python: 
python --version
echo   Virtual environment: Active
echo   Dependencies: Installed
echo   Fitbit Client ID: %FITBIT_CLIENT_ID:~0,10%...
echo   Fitbit Client Secret: %FITBIT_CLIENT_SECRET:~0,10%...
if "%FITBIT_REDIRECT_URI%"=="" (
    set FITBIT_REDIRECT_URI=http://localhost:5000/fitbit/callback
)
echo   Redirect URI: %FITBIT_REDIRECT_URI%
echo ============================================================
echo.

REM Start the Flask application
echo Starting Flask application...
echo.
echo Server will be available at:
echo   Dashboard: http://localhost:5000/
echo   Help:      http://localhost:5000/help
echo.
echo Press Ctrl+C to stop the server
echo.

python -m backend.app

pause

