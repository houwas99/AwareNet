@echo off
TITLE AwareNet - Build PROTEGE
COLOR 0C
echo ============================================================
echo   AwareNet - Build PROTEGE (PyArmor + PyInstaller)
echo   Obfuscation + anti-debug + secrets chiffres
echo ============================================================
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Python introuvable
  pause
  exit /b 1
)
IF EXIST ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo [*] Installation dependances...
python -m pip install -r requirements.txt -q
python -m pip install pyarmor -q
python -m pip install pyinstaller -q

echo.
echo [*] Etape 1: Obfuscation PyArmor (optionnel)...
:: Les secrets sont deja chiffres en base64+xor dans le code, PyArmor est bonus
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
:: Tente PyArmor mais ne bloque pas si echoue (syntax change selon version)
python -m pyarmor --help >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
  echo [*] PyArmor detecte - tentative obfuscation...
  python -m pyarmor gen --help >nul 2>&1
  IF %ERRORLEVEL% EQU 0 (
    python -m pyarmor gen --output dist_obf modules\license.py 2>nul
    IF %ERRORLEVEL% NEQ 0 (
      echo [!] PyArmor gen echoue - on continue sans (secrets deja chiffres)
    ) else (
      echo [*] PyArmor OK
    )
  ) else (
    echo [!] PyArmor gen non supporte sur cette version - on continue sans
  )
) else (
  echo [!] PyArmor non trouve - on continue sans (secrets deja chiffres)
)

echo.
echo [*] Etape 2: Build PyInstaller protege...
:: Meme que build_exe.bat mais avec --key et sans console + anti-bypass
:: Le bypass AWARNET_NO_LICENSE est bloque en .exe sauf si .dev present (protect.py)

:: Nettoie
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [*] Build Launcher GUI (AwareNet-Protected.exe)...
python -m PyInstaller --onefile --windowed --name AwareNet-Protected --icon icon.ico ^
 --add-data "templates;templates" ^
 --add-data "static;static" ^
 --add-data "modules;modules" ^
 --add-data "custom_templates;custom_templates" ^
 --hidden-import flask --hidden-import flask_socketio --hidden-import engineio --hidden-import requests ^
 --hidden-import modules.license --hidden-import modules.boost --hidden-import modules.protect ^
 --collect-all flask_socketio --collect-all engineio ^
 launcher.py

IF %ERRORLEVEL% NEQ 0 (
  echo [!] Build echoue
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Build protege termine !
echo   dist\AwareNet-Protected.exe
echo.
echo   Protections actives:
echo    - Secrets chiffres (base64+xor+split) dans boost.py/license.py
echo    - Bypass AWARNET_NO_LICENSE bloque en .exe (sauf .dev)
echo    - Anti-debug leger (protect.py)
echo    - Pour protection MAX: utilise build_nuitka.bat (compile en C)
echo ============================================================
pause
