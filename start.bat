@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   NetOps Dashboard Launcher
echo ============================================
echo.

:: ---- Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [..] Python is not installed. Attempting to install via winget...
    echo.
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install Python automatically.
        echo         Please install it manually from https://www.python.org/downloads/
        echo         Make sure to check "Add Python to PATH" during install.
        echo.
        echo         If you already installed Python, disable the Windows Store
        echo         alias in: Settings ^> Apps ^> Advanced app settings ^> App execution aliases
        pause
        exit /b 1
    )
    echo [OK] Python installed successfully.
    echo.
    echo ============================================
    echo   Python was just installed. PATH needs to
    echo   be refreshed. Please CLOSE this window
    echo   and run start.bat again.
    echo ============================================
    pause
    exit /b 0
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Found %PYVER%

:: ---- Create venv if needed (recreate if broken) ----
if not exist "venv\Scripts\pip.exe" goto :createvenv
echo [OK] Virtual environment already exists.
goto :venvready

:createvenv
if exist "venv\" (
    echo [..] Existing venv is broken — recreating...
    rmdir /s /q venv
)
echo [..] Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment created.

:venvready
set VENV_PYTHON=venv\Scripts\python.exe
set VENV_PIP=venv\Scripts\pip.exe

:: ---- Install Python dependencies ----
echo [..] Installing Python dependencies...
%VENV_PIP% install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install Python dependencies.
    pause
    exit /b 1
)
echo [OK] Python dependencies installed.

:: ---- Check Node/npm ----
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] npm is not installed or not in PATH. Skipping Node dependencies.
    echo         This is optional — install Node.js from https://nodejs.org/ if needed.
    goto :nodeready
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo [OK] Found Node %NODEVER%
echo [..] Installing Node dependencies...
call npm install --silent
if %errorlevel% neq 0 (
    echo [WARN] npm install had issues, but continuing anyway.
) else (
    echo [OK] Node dependencies installed.
)

:nodeready

:: ---- Copy .env.example to .env if needed ----
if exist ".env" goto :envready
if not exist ".env.example" goto :envready
copy ".env.example" ".env" >nul
echo [OK] Created .env from .env.example — review and edit as needed.
:envready
if exist ".env" echo [OK] .env file ready.

:: ---- Prompt for port ----
echo.
set /p DASHBOARD_PORT="Enter port number [7000]: "
if "!DASHBOARD_PORT!"=="" set DASHBOARD_PORT=7000

:: ---- Write chosen port into .env so app.py and all services use it ----
if exist ".env" (
    findstr /v /b "DASHBOARD_PORT=" .env > .env.tmp
    echo DASHBOARD_PORT=!DASHBOARD_PORT!>> .env.tmp
    move /y .env.tmp .env >nul
    echo [OK] Port set to !DASHBOARD_PORT! in .env
)

echo.
echo ============================================
echo   Starting dashboard on port !DASHBOARD_PORT!...
echo ============================================
echo.

:: ---- Launch the dashboard in the background ----
set DASHBOARD_PORT=!DASHBOARD_PORT!
start "" /b venv\Scripts\pythonw.exe dashboard\app.py

:: ---- Wait for the server to start, then open the browser ----
echo [..] Waiting for server to start...
timeout /t 3 /nobreak >nul
start "" http://localhost:!DASHBOARD_PORT!
echo [OK] Dashboard is running in the background on port !DASHBOARD_PORT!
echo      Your browser should open automatically.
echo      If not, open http://localhost:!DASHBOARD_PORT! manually.
echo.
echo      To stop it, close the process from Task Manager or run:
echo        taskkill /f /im pythonw.exe
echo.
pause

endlocal
