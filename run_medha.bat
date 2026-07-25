@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo       MEDHA AI - STARTING APPLICATION
echo ==========================================

set BACKEND_PORT=8010
set FRONTEND_PORT=3000

start "MEDHA Backend" cmd /k "cd /d %~dp0backend && call venv\Scripts\activate.bat && python -m uvicorn main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"
start "MEDHA Frontend" cmd /k "cd /d %~dp0frontend & if not exist node_modules npm install & set PORT=%FRONTEND_PORT% & npm start"

REM Give the React dev server time to compile before opening the browser
timeout /t 30 >nul
start "" "http://localhost:%FRONTEND_PORT%"

endlocal