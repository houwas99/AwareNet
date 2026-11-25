@echo off
TITLE AwareNet - Build NUITKA (MAX protection)
COLOR 0A
echo ============================================================
echo   AwareNet - Build NUITKA (compilation C)
echo   Protection MAX contre decompilation
echo ============================================================
echo.
echo  Nuitka compile le Python en C -> pas de .pyc extractible
echo  C'est la meilleure protection pour .exe Python
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
  echo [!] Python introuvable
  pause
  exit /b 1
)
IF EXIST ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo [*] Installation...
python -m pip install -r requirements.txt -q
python -m pip install nuitka -q
python -m pip install zstandard ordered-set -q

echo.
echo [*] Build Nuitka (peut prendre 5-10 min)...
python -m nuitka --onefile --windows-disable-console --windows-icon-from-ico=icon.ico ^
 --enable-plugin=tk-inter ^
 --include-data-dir=templates=templates ^
 --include-data-dir=static=static ^
 --include-data-dir=modules=modules ^
 --include-data-dir=custom_templates=custom_templates ^
 --output-filename=AwareNet-Nuitka.exe ^
 --output-dir=dist ^
 launcher.py

IF %ERRORLEVEL% NEQ 0 (
  echo [!] Build Nuitka echoue - essaie build_protected.bat
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Build Nuitka termine !
echo   dist\AwareNet-Nuitka.exe
echo   -> Vrai binaire C, pas de .pyc, reverse tres difficile
echo ============================================================
pause
