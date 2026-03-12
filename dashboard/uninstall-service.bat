@echo off
:: Run this as Administrator to remove the dashboard service

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Run this script as Administrator
    pause
    exit /b 1
)

set SERVICE_NAME=SystemControlDashboard

nssm stop %SERVICE_NAME%
nssm remove %SERVICE_NAME% confirm

echo.
echo Service "%SERVICE_NAME%" removed.
pause
