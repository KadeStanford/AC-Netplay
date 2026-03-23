@echo off
setlocal
title AC-Netplay Host

echo ================================================
echo  AC-Netplay Host Launcher
echo ================================================
echo.

set "INSTALL_DIR=%USERPROFILE%\AC-Netplay"
set "TARGET_PS1=%INSTALL_DIR%\tools\windows\start_host_one_click.ps1"

if not exist "%TARGET_PS1%" (
    echo Downloading AC-Netplay to %INSTALL_DIR% ...
    echo.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "if (Get-Command git -ErrorAction SilentlyContinue) { git clone --depth 1 https://github.com/KadeStanford/AC-Netplay.git '%INSTALL_DIR%' } else { New-Item -ItemType Directory -Path '%INSTALL_DIR%' -Force | Out-Null; $t=Join-Path $env:TEMP 'acnp.zip'; Invoke-WebRequest 'https://codeload.github.com/KadeStanford/AC-Netplay/zip/refs/heads/main' -OutFile $t; $x=Join-Path $env:TEMP 'acnp_extract'; Expand-Archive $t $x -Force; Copy-Item (Join-Path $x 'AC-Netplay-main' '*') '%INSTALL_DIR%' -Recurse -Force }"
    echo.
)

if not exist "%TARGET_PS1%" (
    echo [ERROR] Could not download AC-Netplay. Check your internet connection.
    goto :done
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TARGET_PS1%"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The script exited with code %ERRORLEVEL%
    echo Check the output above for details.
)

:done
echo.
echo ================================================
echo  Script finished. Press any key to close.
echo ================================================
pause >nul
