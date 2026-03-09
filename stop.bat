@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   NetOps Dashboard - Stop Server
echo ============================================
echo.

:: ---- Read port from .env if available ----
set DASHBOARD_PORT=7000
if exist ".env" (
    for /f "tokens=2 delims==" %%a in ('findstr /b "DASHBOARD_PORT=" .env') do set DASHBOARD_PORT=%%a
)

:: ---- Find and kill processes on the dashboard port ----
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano -p TCP 2^>nul ^| findstr ":!DASHBOARD_PORT! " ^| findstr "LISTENING"') do (
    if %%p neq 0 (
        echo [..] Killing process %%p on port !DASHBOARD_PORT!...
        taskkill /f /t /pid %%p >nul 2>&1
        set FOUND=1
    )
)

if !FOUND!==1 (
    echo [OK] Dashboard server stopped.
) else (
    echo [--] No server found running on port !DASHBOARD_PORT!.
)

echo.
pause
endlocal
