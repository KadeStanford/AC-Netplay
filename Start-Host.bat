@echo off
setlocal
title AC-Netplay Host

echo ================================================
echo  AC-Netplay Host Launcher
echo ================================================
echo.

set "INSTALL_DIR=%USERPROFILE%\AC-Netplay"
set "TARGET_PS1=%INSTALL_DIR%\tools\windows\start_host_one_click.ps1"

if not exist "%TARGET_PS1%" goto :download
goto :run

:download
echo Downloading AC-Netplay to %INSTALL_DIR% ...
echo This may take a moment on first run.
echo.
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :git_clone
goto :zip_download

:git_clone
git clone --depth 1 https://github.com/KadeStanford/AC-Netplay.git "%INSTALL_DIR%"
goto :after_download

:zip_download
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; New-Item -ItemType Directory -Path '%INSTALL_DIR%' -Force | Out-Null; $z='%INSTALL_DIR%\setup.zip'; Invoke-WebRequest 'https://codeload.github.com/KadeStanford/AC-Netplay/zip/refs/heads/main' -OutFile $z; Expand-Archive $z '%INSTALL_DIR%\_tmp' -Force; Copy-Item '%INSTALL_DIR%\_tmp\AC-Netplay-main\*' '%INSTALL_DIR%' -Recurse -Force; Remove-Item '%INSTALL_DIR%\_tmp','%INSTALL_DIR%\setup.zip' -Recurse -Force"

:after_download
echo.

:run
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
