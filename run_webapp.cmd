@echo off
setlocal

cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
set "VENV_DIR=.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"

if exist "%PY%" goto deps

echo [YTBulkTranscription] Creating virtual environment in "%CD%\%VENV_DIR%"...
where py >nul 2>&1
if errorlevel 1 (
  python -m venv "%VENV_DIR%"
) else (
  py -3 -m venv "%VENV_DIR%"
)
if errorlevel 1 goto venv_fail

:deps
echo [YTBulkTranscription] Checking dependencies...
"%PY%" -c "import fastapi, uvicorn, yt_dlp, youtube_transcript_api" >nul 2>&1
if not errorlevel 1 goto choose_port

echo [YTBulkTranscription] Installing dependencies (first run only)...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto pip_fail
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto deps_fail

:choose_port
netstat -ano -p tcp | findstr /i /c:":8000" | findstr /i /c:"LISTENING" >nul
if not errorlevel 1 (
  set "PORT=8765"
  echo [YTBulkTranscription] Port 8000 is busy, using %PORT% instead.
)

echo [YTBulkTranscription] Opening http://%HOST%:%PORT%/ ...
start "" "http://%HOST%:%PORT%/"

echo [YTBulkTranscription] Starting server in this window. Press CTRL+C to stop.
"%PY%" -m uvicorn app.main:app --host %HOST% --port %PORT%
set "EXITCODE=%ERRORLEVEL%"

echo.
echo [YTBulkTranscription] Server exited.
echo If the browser still cannot connect, review the error lines above.
pause
exit /b %EXITCODE%

:venv_fail
echo [YTBulkTranscription] ERROR: Failed to create virtual environment.
echo Try installing Python 3.x from python.org, then run this again.
pause
exit /b 1

:pip_fail
echo [YTBulkTranscription] ERROR: pip upgrade failed.
pause
exit /b 1

:deps_fail
echo [YTBulkTranscription] ERROR: dependency install failed.
pause
exit /b 1
