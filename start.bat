@echo off
setlocal
cd /d %~dp0

if not exist .venv (
    echo [fusion-auto] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [fusion-auto] ERROR: Failed to create venv. Make sure Python 3.11+ is installed.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo [fusion-auto] Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [fusion-auto] ERROR: pip install failed.
    pause
    exit /b 1
)

if not exist .env (
    echo [fusion-auto] .env not found - copying .env.example. Edit .env with your API keys before first run.
    copy .env.example .env >nul
)

echo [fusion-auto] Starting server on http://127.0.0.1:8765 ...
start "" http://127.0.0.1:8765
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8765 --reload

endlocal
