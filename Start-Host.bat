@echo off
setlocal
title AC-Netplay Host

echo ================================================
echo  AC-Netplay Host Launcher
echo ================================================
echo.

set "URL=https://raw.githubusercontent.com/KadeStanford/AC-Netplay/main/tools/windows/start_host_one_click.ps1"
set "TMP=%TEMP%\acnp_start_host.ps1"

echo Fetching launcher...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest '%URL%' -OutFile '%TMP%'"

if not exist "%TMP%" (
    echo.
    echo [ERROR] Could not download the launcher. Check your internet connection.
    goto :done
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TMP%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Script exited with code %ERRORLEVEL%.
)

:done
echo.
echo ================================================
echo  Press any key to close.
echo ================================================
pause >nul
