@echo off
:: Run this as Administrator to install the dashboard as a Windows service
:: Requires NSSM - download from https://nssm.cc/download

:: Check for admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Run this script as Administrator
    pause
    exit /b 1
)

:: Check if nssm is available
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: NSSM not found. Download from https://nssm.cc/download
    echo Extract nssm.exe to a folder in your PATH (e.g. C:\Windows)
    pause
    exit /b 1
)

set SERVICE_NAME=SystemControlDashboard
set SCRIPT_DIR=%~dp0

:: Install the service
nssm install %SERVICE_NAME% "%SCRIPT_DIR%venv\Scripts\python.exe" "%SCRIPT_DIR%app.py"
nssm set %SERVICE_NAME% AppDirectory "%SCRIPT_DIR%"
nssm set %SERVICE_NAME% DisplayName "System Control Dashboard"
nssm set %SERVICE_NAME% Description "Home Network Management Dashboard (Flask)"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%SCRIPT_DIR%service.log"
nssm set %SERVICE_NAME% AppStderr "%SCRIPT_DIR%service.log"
nssm set %SERVICE_NAME% AppStdoutCreationDisposition 4
nssm set %SERVICE_NAME% AppStderrCreationDisposition 4
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 1048576

:: Start the service
nssm start %SERVICE_NAME%

echo.
echo Service "%SERVICE_NAME%" installed and started.
echo Dashboard available at http://localhost:9000
echo.
echo Commands:
echo   nssm status %SERVICE_NAME%    - Check status
echo   nssm stop %SERVICE_NAME%      - Stop service
echo   nssm start %SERVICE_NAME%     - Start service
echo   nssm restart %SERVICE_NAME%   - Restart service
echo   nssm remove %SERVICE_NAME%    - Uninstall service
echo.
pause
