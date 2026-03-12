@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   NetOps Dashboard — Launcher
echo ============================================
echo.

set "ROOT=%~dp0"

REM Read DASHBOARD_PORT from .env (default 9000)
set "DASHBOARD_PORT=9000"
if exist "%ROOT%.env" (
    for /f "tokens=1,* delims==" %%a in ('findstr /B "DASHBOARD_PORT" "%ROOT%.env"') do set "DASHBOARD_PORT=%%b"
)

set "REINSTALL=0"
set "TRAY=0"
set "INSTALL=0"
set "UNINSTALL=0"
set "RUN=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--reinstall" set "REINSTALL=1"
if /I "%~1"=="--tray" set "TRAY=1"
if /I "%~1"=="--install" set "INSTALL=1"
if /I "%~1"=="--uninstall" set "UNINSTALL=1"
if /I "%~1"=="--run" set "RUN=1"
shift
goto parse_args
:args_done

REM --- Detect all-in-one dashboard.exe ---
if exist "%ROOT%dashboard.exe" goto allinone_mode
goto check_exe_mode

REM ==========================================================
REM   ALL-IN-ONE MODE — single dashboard.exe, just launch it
REM ==========================================================
:allinone_mode
echo [OK] All-in-one dashboard.exe detected

REM --- .env check ---
if not exist "%ROOT%.env" (
    if exist "%ROOT%.env.example" (
        copy /Y "%ROOT%.env.example" "%ROOT%.env" >nul
        echo.
        echo ============================================
        echo   ACTION REQUIRED: Configure .env
        echo ============================================
        echo   A .env file has been created from the example.
        echo   Edit "%ROOT%.env" with your credentials
        echo   before the dashboard can connect to your systems.
        echo ============================================
        echo.
        pause
    ) else (
        echo [WARN] No .env or .env.example found.
    )
) else (
    echo [OK] .env file exists
)

echo.
echo ============================================
echo   Starting Dashboard [all-in-one]...
echo   Look for the tray icon in your taskbar.
echo   URL: http://localhost:%DASHBOARD_PORT%
echo ============================================
start "" "%ROOT%dashboard.exe"
echo.
echo   Dashboard is running. You can close this window.
echo.
timeout /t 3 /nobreak >nul
endlocal
exit

:check_exe_mode
REM --- Detect legacy .exe mode ---
set "EXE_MODE=0"
if exist "%ROOT%dashboard-service.exe" set "EXE_MODE=1"

REM ==========================================================
REM   .EXE MODE — standalone executables, no Python needed
REM ==========================================================
if "%EXE_MODE%"=="0" goto python_mode

echo [OK] Standalone .exe detected

REM --- .env check ---
if not exist "%ROOT%.env" (
    if exist "%ROOT%.env.example" (
        copy /Y "%ROOT%.env.example" "%ROOT%.env" >nul
        echo.
        echo ============================================
        echo   ACTION REQUIRED: Configure .env
        echo ============================================
        echo   A .env file has been created from the example.
        echo   Edit "%ROOT%.env" with your credentials
        echo   before the dashboard can connect to your systems.
        echo ============================================
        echo.
        pause
    ) else (
        echo [WARN] No .env or .env.example found.
    )
) else (
    echo [OK] .env file exists
)

REM --- Console run mode (for debugging) ---
if "%RUN%"=="1" (
    echo.
    echo ============================================
    echo   Running Dashboard in console mode
    echo   (not as a service — for debugging)
    echo ============================================
    echo.
    cd /d "%ROOT%"
    "%ROOT%dashboard-service.exe" run
    echo.
    echo   Server exited.
    pause
    endlocal
    exit /b 0
)

REM --- Uninstall service ---
if "%UNINSTALL%"=="1" (
    echo.
    echo   Uninstalling service...
    net stop SystemControlDashboard >nul 2>&1
    "%ROOT%dashboard-service.exe" remove >nul 2>&1
    echo   [OK] Service removed.
    echo.
    pause
    endlocal
    exit /b 0
)

REM --- Install service ---
if "%INSTALL%"=="1" (
    echo.
    echo   Installing service...
    "%ROOT%dashboard-service.exe" --startup auto install
    if !errorlevel! neq 0 (
        echo   [ERROR] Failed to install service. Run as Administrator.
        pause
        endlocal
        exit /b 1
    )
    echo   [OK] Service installed.
    echo   Starting service...
    net start SystemControlDashboard
    if !errorlevel! neq 0 (
        echo.
        echo   [ERROR] Service failed to start.
        echo   Try:  start.bat --run   to see error output in console.
        echo   Logs: %ROOT%logs\service_crash.log
        pause
        endlocal
        exit /b 1
    )
    echo.
    echo   URL: http://localhost:%DASHBOARD_PORT%
    start "" http://localhost:%DASHBOARD_PORT%
    echo.
    if "%TRAY%"=="1" (
        echo   Starting tray icon...
        if exist "%ROOT%dashboard-tray.exe" (
            start "" "%ROOT%dashboard-tray.exe"
        )
    )
    echo   Done. Service is running.
    echo.
    timeout /t 3 /nobreak >nul
    endlocal
    exit /b 0
)

REM --- Tray mode (exe) ---
if "%TRAY%"=="1" (
    echo.
    echo ============================================
    echo   Starting Dashboard [tray mode]...
    echo   Look for the tray icon in your taskbar.
    echo   URL: http://localhost:%DASHBOARD_PORT%
    echo ============================================
    if exist "%ROOT%dashboard-tray.exe" (
        start "" "%ROOT%dashboard-tray.exe"
    ) else (
        echo   [WARN] dashboard-tray.exe not found
    )
    echo.
    echo   Tray is running. You can close this window.
    echo.
    timeout /t 5 /nobreak >nul
    endlocal
    exit
)

REM --- Default exe mode: start service + tray ---
echo.
echo ============================================
echo   Starting Dashboard [service + tray]...
echo   URL: http://localhost:%DASHBOARD_PORT%
echo ============================================
REM Check if service is installed
sc query SystemControlDashboard >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo   Service not installed. Installing now...
    echo   (You may see a UAC prompt)
    "%ROOT%dashboard-service.exe" --startup auto install
    if !errorlevel! neq 0 (
        echo   [ERROR] Failed to install service. Run as Administrator.
        pause
        endlocal
        exit /b 1
    )
    echo   [OK] Service installed.
)
net start SystemControlDashboard >nul 2>&1
if !errorlevel! neq 0 (
    REM Check if it's already running
    sc query SystemControlDashboard | findstr "RUNNING" >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo   [ERROR] Service failed to start.
        echo   Try:  start.bat --run   to see error output in console.
        echo   Logs: %ROOT%logs\service_crash.log
        pause
        endlocal
        exit /b 1
    )
)
echo   [OK] Service started.
start "" http://localhost:%DASHBOARD_PORT%
if exist "%ROOT%dashboard-tray.exe" (
    start "" "%ROOT%dashboard-tray.exe"
    echo   [OK] Tray icon started.
)
echo.
echo   Dashboard is running as a Windows service.
echo   Use the tray icon to manage, or:
echo     start.bat --run          Run in console (debug)
echo     start.bat --uninstall    Remove service
echo.
timeout /t 5 /nobreak >nul
endlocal
exit

REM ==========================================================
REM   PYTHON MODE — fallback when .exe not available
REM ==========================================================
:python_mode

REM --- Step 1: Find Python ---
set "PYTHON="

python --version >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=python"
    goto python_found
)

py --version >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON=py"
    goto python_found
)

echo [ERROR] Python not found on PATH.
echo.
echo   Please install Python 3.10+ from https://www.python.org/downloads/
echo   During installation, check "Add Python to PATH".
echo   Then re-run this script.
echo.
pause
exit /b 1

:python_found
echo [OK] Python found: %PYTHON%
%PYTHON% --version

REM --- Step 2: Virtual Environment ---
if exist "%ROOT%dashboard\venv\Scripts\activate.bat" (
    echo [OK] Virtual environment exists
    call "%ROOT%dashboard\venv\Scripts\activate.bat"
    goto venv_ready
)

echo [..] Creating virtual environment...
%PYTHON% -m venv "%ROOT%dashboard\venv"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
call "%ROOT%dashboard\venv\Scripts\activate.bat"
set "REINSTALL=1"
echo [OK] Virtual environment created

:venv_ready

REM --- Step 3: Install Dependencies ---
if "%REINSTALL%"=="1" (
    echo [..] Installing dependencies...
    pip install -r "%ROOT%requirements.txt" --quiet
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
) else (
    echo [OK] Dependencies already installed (use --reinstall to force)
)

REM --- Step 4: Create .env if Missing ---
if not exist "%ROOT%.env" (
    if exist "%ROOT%.env.example" (
        copy /Y "%ROOT%.env.example" "%ROOT%.env" >nul
        echo.
        echo ============================================
        echo   ACTION REQUIRED: Configure .env
        echo ============================================
        echo   A .env file has been created from the example.
        echo   Edit "%ROOT%.env" with your credentials
        echo   before the dashboard can connect to your systems.
        echo ============================================
        echo.
        pause
    ) else (
        echo [WARN] No .env or .env.example found. Dashboard may not connect to systems.
    )
) else (
    echo [OK] .env file exists
)

REM --- Step 5: Start the Server ---
echo.
echo ============================================
if "%TRAY%"=="1" (
    echo   Starting Dashboard [tray mode]...
    echo   Look for the tray icon in your taskbar.
    echo   URL: http://localhost:%DASHBOARD_PORT%
    echo ============================================
    cd /d "%ROOT%dashboard"
    start "" http://localhost:%DASHBOARD_PORT%
    start /min "" %PYTHON% tray.py
    echo.
    echo   Tray is running. You can close this window.
    echo.
    timeout /t 5 /nobreak >nul
    endlocal
    exit
) else (
    echo   Starting Dashboard...
    echo.
    echo   URL:  http://localhost:%DASHBOARD_PORT%
    echo.
    echo   Press Ctrl+C to stop the server.
    echo ============================================
    echo.
    cd /d "%ROOT%dashboard"
    REM Open browser after a short delay to let server start
    start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:%DASHBOARD_PORT%"
    %PYTHON% app.py
)

echo.
echo [ERROR] Server exited unexpectedly.
echo.
pause
endlocal
