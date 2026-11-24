@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  ITstudy V6.0.0  Launch Script
::  Copyright (C) 2025-2026 YINJUN
:: ============================================================

title ITstudy V6.0.0 Server
cd /d "%~dp0"

echo.
echo ================================================
echo   ITstudy V6.0.0 - Startup
echo ================================================
echo.

:: -- 1. detect Python --
echo [1/7] Checking Python ...

python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found.
    echo   Please install Python 3.10+: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo   Python %PYVER% - OK

:: -- 2. detect PostgreSQL --
echo.
echo [2/7] Checking PostgreSQL ...

"%SystemRoot%\System32\where.exe" pg_isready >nul 2>&1
if not errorlevel 1 (
    pg_isready -h localhost -p 5432 -q
    if not errorlevel 1 (
        echo   PostgreSQL - OK
    ) else (
        echo   [WARN] PostgreSQL installed but not responding on localhost:5432
        echo   -----------------------------------------------------
        echo     Start the PostgreSQL service and ensure port 5432 is open.
        echo     pg_isready reports: service unavailable
        echo   -----------------------------------------------------
    )
) else (
    echo   [INFO] pg_isready not found in PATH.
    echo   -----------------------------------------------------
    echo     PostgreSQL client tools not detected. Make sure PostgreSQL
    echo     is installed and the bin directory is in your PATH.
    echo     Download: https://www.postgresql.org/download/windows/
    echo   -----------------------------------------------------
)

:: -- 3. detect Node.js --
echo.
echo [3/7] Checking Node.js ...

node --version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=1 delims=v" %%v in ('node --version 2^>^&1') do set "NODEVER=%%v"
    echo   Node.js v!NODEVER! - OK
) else (
    echo   [WARN] Node.js not found.
    echo   -----------------------------------------------------
    echo     Node.js is recommended for frontend tooling.
    echo     Download: https://nodejs.org/
    echo     China mirror: https://npmmirror.com/mirrors/node/
    echo   -----------------------------------------------------
    echo.
)

:: -- 4. check dependencies & venv --
echo.
echo [4/7] Checking dependencies ...

set "USE_VENV=0"
set "PYTHON_EXE=python"

python -c "import flask, waitress, flask_sqlalchemy, flask_migrate, flask_caching, flask_compress, pydantic, openpyxl, PIL, psycopg2, requests, cryptography, pptx" >nul 2>&1
if not errorlevel 1 goto DEPS_OK

echo   Missing packages detected, setting up venv ...

:: create venv if not exists
if not exist "%~dp0venv\Scripts\python.exe" (
    echo   Creating virtual environment ...
    python -m venv "%~dp0venv"
    if errorlevel 1 (
        echo   [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
) else (
    echo   Using existing venv
)

set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
set "PIP_EXE=%~dp0venv\Scripts\pip.exe"

echo   Upgrading pip ...
call "!PYTHON_EXE!" -m pip install --upgrade pip -q
if errorlevel 1 (
    echo   [WARN] pip upgrade failed, continuing ...
)

echo   Installing packages - Tsinghua mirror ...
call "!PIP_EXE!" install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo   [RETRY] Aliyun mirror ...
    call "!PIP_EXE!" install -r "%~dp0requirements.txt" -i https://mirrors.aliyun.com/pypi/simple/
    if errorlevel 1 (
        echo   [RETRY] Default PyPI ...
        call "!PIP_EXE!" install -r "%~dp0requirements.txt"
        if errorlevel 1 (
            echo   [ERROR] Package installation failed.
            pause
            exit /b 1
        )
    )
)

echo   Verifying ...
call "!PYTHON_EXE!" -c "import flask, waitress, flask_sqlalchemy, flask_migrate, flask_caching, flask_compress, pydantic, openpyxl, PIL, psycopg2, requests, cryptography, pptx" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Dependency check failed after install.
    pause
    exit /b 1
)
set "USE_VENV=1"
echo   Dependencies installed in venv OK
goto DEPS_READY

:DEPS_OK
echo   Dependencies OK - global Python

:DEPS_READY
:: -- 5. static optimize (skipped by default; no interactive prompt for service mode) --
echo.
echo [5/7] Static resource optimization ... Skipped - service mode

:: -- 6. DB migration --
echo.
echo [6/7] Running database migration - flask db upgrade ...

set "FLASK_APP=app:create_app"
call "!PYTHON_EXE!" -m flask db upgrade 2>&1
if errorlevel 1 (
    echo   [WARN] DB migration had issues; server will still attempt to start.
    echo   Fresh NSIS installs may ignore this: tables are created by
    echo   create_app, and alembic not being stamped is expected.
)

:: -- 7. start server --
echo.
echo [7/7] Starting Waitress server ...
if "!USE_VENV!"=="1" (
    echo   Using venv Python
)
echo.
echo ================================================
echo   http://localhost:5000         - HTML frontend
echo   Press Ctrl+C to stop
echo ================================================
echo.

call "!PYTHON_EXE!" -c "from waitress import serve; from app import create_app; app=create_app(); print('Serving on http://0.0.0.0:5000 (threads=%s)' % app.config['WAITRESS_THREADS']); serve(app, listen='0.0.0.0:5000', threads=app.config['WAITRESS_THREADS'], connection_limit=400, channel_timeout=120)"

if errorlevel 1 (
    echo.
    echo [ERROR] Server failed to start.
    pause
    exit /b 1
)

pause
