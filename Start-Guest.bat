@echo off
setlocal
title AC-Netplay Guest

echo ================================================
echo  AC-Netplay Guest Launcher
echo ================================================
echo.
echo Fetching and running launcher...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $r = Invoke-WebRequest 'https://raw.githubusercontent.com/KadeStanford/AC-Netplay/main/tools/windows/start_guest_one_click.ps1' -UseBasicParsing; if (-not $r -or -not $r.Content) { throw 'Download failed - check your internet connection' }; & ([scriptblock]::Create($r.Content))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Script exited with code %ERRORLEVEL%.
)

echo.
echo ================================================
echo  Press any key to close.
echo ================================================
pause >nul
