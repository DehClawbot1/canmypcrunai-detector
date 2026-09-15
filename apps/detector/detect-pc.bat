@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title CanMyPCRunAI Hardware Compatibility Detector

echo ==================================================
echo   CanMyPCRunAI Hardware Detector for Windows
echo ==================================================
echo.

rem Production is the safe default for downloaded fallback scripts.
rem A custom URL can still be supplied as the second argument for local/dev use.
set "SERVER_URL=https://canmypcrunai.online"
if not "%~2"=="" set "SERVER_URL=%~2"

if not exist "%~dp0detect-pc.ps1" (
    echo [INFO] detect-pc.ps1 not found locally. Downloading from %SERVER_URL%...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '%SERVER_URL%/download/detect-pc.ps1' -OutFile '%~dp0detect-pc.ps1' -UseBasicParsing"
    if not exist "%~dp0detect-pc.ps1" (
        echo [ERROR] Failed to download detect-pc.ps1. Please check your connection to %SERVER_URL%
        pause
        exit /b 1
    )
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0detect-pc.ps1" %*

pause
