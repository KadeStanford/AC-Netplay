@echo off
setlocal
title AC-Netplay Host

echo ================================================
echo  AC-Netplay Host Launcher
echo ================================================
echo.

set "PS1_SCRIPT=%~dp0tools\windows\start_host_one_click.ps1"
set "INSTALL_DIR=%USERPROFILE%\AC-Netplay"
set "INSTALL_SCRIPT=%INSTALL_DIR%\tools\windows\start_host_one_click.ps1"

if exist "%PS1_SCRIPT%" (
    set "TARGET_PS1=%PS1_SCRIPT%"
    goto :run
)

if exist "%INSTALL_SCRIPT%" (
    set "TARGET_PS1=%INSTALL_SCRIPT%"
    goto :run
)

echo Repo not found next to this file. Downloading AC-Netplay to %INSTALL_DIR% ...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "if (Get-Command git -ErrorAction SilentlyContinue) { git clone --depth 1 https://github.com/KadeStanford/AC-Netplay.git '%INSTALL_DIR%' } else { $z='%INSTALL_DIR%'; New-Item -ItemType Directory -Path $z -Force | Out-Null; $t=Join-Path $env:TEMP 'acnp.zip'; Invoke-WebRequest 'https://codeload.github.com/KadeStanford/AC-Netplay/zip/refs/heads/main' -OutFile $t; Expand-Archive $t (Join-Path $env:TEMP 'acnp') -Force; Copy-Item (Join-Path $env:TEMP 'acnp\AC-Netplay-main\*') $z -Recurse -Force }"

if not exist "%INSTALL_SCRIPT%" (
    echo.
    echo [ERROR] Download failed. Could not find the script at:
    echo   %INSTALL_SCRIPT%
    goto :done
)
set "TARGET_PS1=%INSTALL_SCRIPT%"

:run
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
