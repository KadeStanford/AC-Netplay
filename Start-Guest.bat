@echo off
setlocal
title AC-Netplay Guest

echo ================================================
echo  AC-Netplay Guest Launcher
echo ================================================
echo.

set "INSTALL_DIR=%USERPROFILE%\AC-Netplay"
set "TARGET_PS1=%INSTALL_DIR%\tools\windows\start_guest_one_click.ps1"

if not exist "%TARGET_PS1%" (
    echo Downloading AC-Netplay to %INSTALL_DIR% ...
    echo This may take a moment on first run.
    echo.
    if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; if (Get-Command git -ErrorAction SilentlyContinue) { git clone --depth 1 'https://github.com/KadeStanford/AC-Netplay.git' '%INSTALL_DIR%' } else { New-Item -ItemType Directory '%INSTALL_DIR%' -Force | Out-Null; $z='%INSTALL_DIR%\setup.zip'; Invoke-WebRequest 'https://codeload.github.com/KadeStanford/AC-Netplay/zip/refs/heads/main' -OutFile $z; Expand-Archive $z '%INSTALL_DIR%\_tmp' -Force; Copy-Item '%INSTALL_DIR%\_tmp\AC-Netplay-main\*' '%INSTALL_DIR%' -Recurse -Force; Remove-Item '%INSTALL_DIR%\_tmp','%INSTALL_DIR%\setup.zip' -Recurse -Force }"
    echo.
)

if not exist "%TARGET_PS1%" (
    echo [ERROR] Download failed. Check your internet connection and try again.
    goto :done
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TARGET_PS1%"

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
