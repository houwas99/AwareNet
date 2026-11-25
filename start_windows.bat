@echo off
TITLE AwareNet Launcher
COLOR 0A

echo ===========================================================
echo       AwareNet - Automated Windows Launcher By Houwas        
echo ===========================================================

:: Check if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [!] Python n'est pas installe ou n'est pas dans le PATH.
    echo [!] Veuillez installer Python depuis le Microsoft Store ou python.org.
    pause
    exit /b
)

:: Activate virtual environment if it exists
IF EXIST ".venv\Scripts\activate.bat" (
    echo [*] Activation de l'environnement virtuel...
    call .venv\Scripts\activate.bat
) ELSE IF EXIST "venv\Scripts\activate.bat" (
    echo [*] Activation de l'environnement virtuel...
    call venv\Scripts\activate.bat
)

:: Install requirements automatically
echo [*] Verification des dependances...
pip install -r requirements.txt -q
IF %ERRORLEVEL% NEQ 0 (
    pip install flask flask-socketio pyotp qrcode[pil] -q
)

:: Run the server
echo [*] Lancement du serveur AwareNet sur 0.0.0.0:5000...
echo.
python app.py

pause