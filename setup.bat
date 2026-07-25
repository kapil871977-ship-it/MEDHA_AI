@echo off
echo ==========================================
echo       MEDHA AI - INITIALIZING SETUP
echo ==========================================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)
echo Python found!

REM Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js from https://nodejs.org/
    pause
    exit /b 1
)
echo Node.js found!

:: Backend Setup
echo [1/3] Creating Backend folders and installing Python libraries...
if not exist backend mkdir backend
cd backend

REM Create virtual environment
if not exist venv (
    echo Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
) else (
    call venv\Scripts\activate.bat
)

REM Generate requirements.txt only if missing; otherwise keep the version-controlled one
if not exist requirements.txt (
    echo fastapi> requirements.txt
    echo uvicorn>> requirements.txt
    echo python-dotenv>> requirements.txt
    echo google-generativeai>> requirements.txt
    echo openai>> requirements.txt
    echo pyswisseph==2.10.3.2>> requirements.txt
    echo timezonefinder==8.2.1>> requirements.txt
    echo httpx>> requirements.txt
)
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install Python packages
    cd ..
    pause
    exit /b 1
)
cd ..

:: Frontend Setup
echo [2/3] Creating Frontend (React App)... Yeh 2-5 mins lega...
if not exist frontend (
    echo Y | npx create-react-app frontend
    if errorlevel 1 (
        echo ERROR: Failed to create React app
        pause
        exit /b 1
    )
) else (
    echo Frontend folder already exists, skipping...
)

echo ==========================================
echo    SETUP COMPLETE! AB KUNDLI DEKHEGI...
echo ==========================================
pause