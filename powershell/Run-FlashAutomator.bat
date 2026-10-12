@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================================
echo   Flash Automator - Windows 7 / 10 / 11 PowerShell Engine
echo ==========================================================
echo.

if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FlashAutomator.ps1" -Mode Help
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FlashAutomator.ps1" %*
)

set EXITCODE=%ERRORLEVEL%
if %EXITCODE% NEQ 0 (
    echo.
    echo [ERROR] Flash Automator finished with error code %EXITCODE%
)
endlocal
exit /b %EXITCODE%
