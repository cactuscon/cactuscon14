@echo off
setlocal enabledelayedexpansion
REM Flash a combined ESP32-S3 firmware binary at 0x0.
REM For split image layouts, use flash_esp32s3.bat.

cd /d "%~dp0"
set "BIN_NAME=ESP32_GENERIC_S3-20241129-v1.24.1.bin"

if not exist "%BIN_NAME%" (
    echo Error: %BIN_NAME% not found in %CD%
    pause
    exit /b 1
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found in PATH
    pause
    exit /b 1
)

python -m esptool version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: esptool is required. Install with: python -m pip install esptool
    pause
    exit /b 1
)

if "%PORT%"=="" (
    for %%p in (COM3 COM4 COM5 COM6 COM7 COM8 COM9 COM10 COM11 COM12) do (
        mode %%p >nul 2>&1
        if !errorlevel! equ 0 (
            set "PORT=%%p"
            goto :found_port
        )
    )
)

:found_port
if "%PORT%"=="" (
    echo Error: could not auto-detect serial port.
    echo Set PORT manually, e.g.: set PORT=COM5 ^&^& flash_bin.bat
    pause
    exit /b 1
)

echo Flashing combined ESP32-S3 firmware
echo   binary: %BIN_NAME%
echo   port:   %PORT%
echo.

python -m esptool --chip esp32s3 --port %PORT% --baud 460800 write_flash 0x0 "%BIN_NAME%"
if %errorlevel% neq 0 (
    echo.
    echo Flash failed.
    pause
    exit /b 1
)

echo.
echo Flash complete.
echo If this image does not match your board layout, use flash_esp32s3.bat.
pause
