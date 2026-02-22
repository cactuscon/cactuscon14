@echo off
setlocal
REM Development OTA Server Runner for CactusCon Badge (Windows)
REM This script starts the development OTA server that watches src/ for changes

cd /d "%~dp0"

if "%DEV_SERVER_HOST%"=="" set "DEV_SERVER_HOST=127.0.0.1"
if "%DEV_SERVER_PORT%"=="" set "DEV_SERVER_PORT=8000"

echo Starting CactusCon Badge Development OTA Server...
echo This will serve files from src/ directory on http://%DEV_SERVER_HOST%:%DEV_SERVER_PORT%/ota/
echo.

REM Check if we're in the badge directory
if not exist "src" (
    echo Error: src/ directory not found. Please run this script from the badge directory.
    pause
    exit /b 1
)

if not exist "dev_ota_server.py" (
    echo Error: dev_ota_server.py not found in %CD%
    pause
    exit /b 1
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found in PATH.
    pause
    exit /b 1
)

REM Start the development server
python dev_ota_server.py --src-dir src --host %DEV_SERVER_HOST% --port %DEV_SERVER_PORT%

echo Server stopped.
pause
