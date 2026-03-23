@echo off
setlocal
title AC-Netplay Guest

echo ================================================
echo  AC-Netplay Guest Launcher
echo ================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\start_guest_one_click.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The script exited with code %ERRORLEVEL%
    echo Check the output above for details.
)

echo.
echo ================================================
echo  Script finished. Press any key to close.
echo ================================================
pause >nul
