@echo off
TITLE AwareNet — Build EXE
COLOR 0A
echo ============================================================
echo   AwareNet — Build EXE avec systeme de cle (PyInstaller)
echo ============================================================
echo.

:: Vérifie Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Python introuvable. Installe Python 3.10+ et ajoute-le au PATH.
  pause
  exit /b 1
)

:: Active venv si existe
IF EXIST ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat
IF EXIST "venv\Scripts\activate.bat" call venv\Scripts\activate.bat

echo [*] Installation des dependances...
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Erreur install pyinstaller
  pause
  exit /b 1
)

:: Demande les infos de licence
echo.
echo ── Configuration de la licence ──
set /p KEY_URL="URL externe pour obtenir la cle (ex: https://tonsite.com/get-key) [defaut: https://example.com/get-awarenet-key]: "
if "%KEY_URL%"=="" set KEY_URL=https://example.com/get-awarenet-key

set /p LICENSE_SECRET="Secret HMAC pour generer les cles [defaut: AwareNet-2026-ChangeMe-SuperSecret-!42]: "
if "%LICENSE_SECRET%"=="" set LICENSE_SECRET=AwareNet-2026-ChangeMe-SuperSecret-!42

set /p LICENSE_SERVER="URL serveur validation online (vide = offline/HWID) [defaut: vide]: "

echo.
echo [*] HWID de cette machine + cle de test:
python -c "from modules.license import get_hwid, generate_key_for_current_machine; print('HWID:', get_hwid()); print('CLE :', generate_key_for_current_machine())" 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [!] Impossible de generer la cle de test — verifie modules/license.py
)

echo.
echo [*] Build PyInstaller...
:: Nettoie anciens builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: Build avec launcher GUI (recommande) — fenetre Tkinter au demarrage
:: Options:
::  --onefile      : un seul .exe
::  --windowed     : sans console (GUI only) — commente si tu veux la console pour debug
::  --name         : nom de l'exe
::  --add-data     : inclure templates/static/modules
::  --hidden-import: Flask/SocketIO
::
:: Variante 1: EXE avec GUI launcher (windowed) — double-clic ouvre la fenetre d'activation
:: Variante 2: EXE console (app.py direct) — garde la console + page /license dans le navigateur
::
echo [*] Mode 1: EXE GUI launcher (AwareNet-Launcher.exe) — windowed
:: --icon ajoute l'icône du .exe (visible sur le Bureau)
set PYI_CMD=python -m PyInstaller --onefile --windowed --name AwareNet-Launcher ^
 --icon icon.ico ^
 --add-data "templates;templates" ^
 --add-data "static;static" ^
 --add-data "modules;modules" ^
 --add-data "custom_templates;custom_templates" ^
 --hidden-import flask --hidden-import flask_socketio --hidden-import engineio --hidden-import eventlet ^
 --hidden-import modules.license --hidden-import modules.database --hidden-import modules.email_sender --hidden-import modules.sms_sender ^
 --collect-all flask_socketio --collect-all engineio

:: Injecte les env au build via --add-data n'est pas possible, on les set au runtime
:: On cree un fichier config au build
echo AWARNET_KEY_URL=%KEY_URL% > .build_config
echo AWARNET_LICENSE_SECRET=%LICENSE_SECRET% >> .build_config
if not "%LICENSE_SERVER%"=="" echo AWARNET_LICENSE_SERVER=%LICENSE_SERVER% >> .build_config

echo [*] Commande: %PYI_CMD% launcher.py
python -m PyInstaller --onefile --windowed --name AwareNet-Launcher --icon icon.ico --add-data "templates;templates" --add-data "static;static" --add-data "modules;modules" --add-data "custom_templates;custom_templates" --hidden-import flask --hidden-import flask_socketio --hidden-import engineio --hidden-import eventlet --hidden-import modules.license --hidden-import modules.database --hidden-import modules.email_sender --hidden-import modules.sms_sender --collect-all flask_socketio --collect-all engineio launcher.py
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Build launcher echoue — essaie en mode console pour voir les erreurs
  pause
  exit /b 1
)

echo.
echo [*] Mode 2: EXE console direct (AwareNet-Console.exe) — avec /license dans navigateur
python -m PyInstaller --onefile --name AwareNet-Console --icon icon.ico --add-data "templates;templates" --add-data "static;static" --add-data "modules;modules" --add-data "custom_templates;custom_templates" --hidden-import flask --hidden-import flask_socketio --hidden-import engineio --collect-all flask_socketio --collect-all engineio app.py
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Build console echoue
)

echo.
echo ============================================================
echo   Build termine !
echo ============================================================
echo   EXE GUI     : dist\AwareNet-Launcher.exe  (double-clic -^> fenetre activation)
echo   EXE Console : dist\AwareNet-Console.exe   (console + http://127.0.0.1:5000/license)
echo.
echo   Config licence au RUNTIME (variables d'env ou .env):
echo     AWARNET_KEY_URL=https://tonsite.com/get-key
echo     AWARNET_LICENSE_SECRET=ton_secret_si_offline
echo     AWARNET_LICENSE_SERVER=https://tonserveur.com/validate (vide=offline)
echo     AWARNET_NO_LICENSE=1  (bypass dev)
echo.
echo   Pour generer une cle pour un HWID client:
echo     python modules\license.py --generate HWID_ICI
echo     python tools\generate_key.py --hwid HWID_ICI
echo.
pause
