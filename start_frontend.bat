@echo off
setlocal
cd /d "%~dp0frontend"

set PORT=%~1
if "%PORT%"=="" set PORT=3000

set BACKEND_PORT=%~2
if "%BACKEND_PORT%"=="" set BACKEND_PORT=8010

echo ------------------------------------------
echo MEDHA Frontend starting...
echo PORT=%PORT%
echo API=http://127.0.0.1:%BACKEND_PORT%
echo ------------------------------------------

if not exist node_modules (
  echo node_modules missing. Running npm.cmd install...
  npm.cmd install
)

set BROWSER=none
set REACT_APP_API_URL=http://127.0.0.1:%BACKEND_PORT%
npm.cmd start

echo.
echo Frontend process exited. Check error above.
pause
endlocal
