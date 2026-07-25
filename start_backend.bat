@echo off
setlocal
cd /d "%~dp0backend"

set PORT=%~1
if "%PORT%"=="" set PORT=8010

set MODEL_TIMEOUT_SECONDS=%~2
if "%MODEL_TIMEOUT_SECONDS%"=="" set MODEL_TIMEOUT_SECONDS=300

echo ------------------------------------------
echo MEDHA Backend starting...
echo PORT=%PORT%
echo MODEL_TIMEOUT_SECONDS=%MODEL_TIMEOUT_SECONDS%
echo ------------------------------------------

"%~dp0backend\venv\Scripts\python.exe" main.py

echo.
echo Backend process exited. Check error above.
pause
endlocal
