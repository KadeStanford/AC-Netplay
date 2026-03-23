@echo off
setlocal
title AC-Netplay Guest

echo ================================================
echo  AC-Netplay Guest Launcher
echo ================================================
echo.
echo Fetching and running launcher...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((Invoke-WebRequest 'https://raw.githubusercontent.com/KadeStanford/AC-Netplay/main/tools/windows/start_guest_one_click.ps1' -UseBasicParsing).Content))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Script exited with code %ERRORLEVEL%.
)

echo.
echo ================================================
echo  Press any key to close.
echo ================================================
pause >nul
