@echo off
setlocal
title Infotainment Lab
echo Opening Infotainment Lab in Debian...
wsl.exe -d Debian --cd "%~dp0." -- bash ./Launch-Linux.sh %*
if errorlevel 1 (
    echo.
    echo Infotainment Lab could not start. The error is shown above.
    echo Startup log: Debian ~/.local/state/tsla-infotainment-lab/launcher.log
    pause
    exit /b 1
)
