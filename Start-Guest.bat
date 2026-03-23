@echo off
setlocal
title AC-Netplay Guest

echo ================================================
echo  AC-Netplay Guest Launcher
echo ================================================
echo.

set "URL=https://raw.githubusercontent.com/KadeStanford/AC-Netplay/main/tools/windows/start_guest_one_click.ps1"
set "PSFILE=%TEMP%\acnp_start_guest.ps1"

if exist "%PSFILE%" del /f /q "%PSFILE%"

echo Fetching launcher...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest '%URL%' -OutFile '%PSFILE%'"

if not exist "%PSFILE%" (
    echo.
    echo [ERROR] Could not download the launcher. Check your internet connection.
    goto :done
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PSFILE%"

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
