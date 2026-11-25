@echo off
TITLE AwareNet - Nettoyage livraison
COLOR 0E
echo ============================================================
echo   AwareNet - Nettoyage complet pour livraison
echo   Supprime toutes les donnees perso/machine
echo ============================================================
echo.

:: DB - tue les process Flask qui lockent
echo [*] Suppression DB...
taskkill /f /im python.exe 2>nul >nul
timeout /t 1 /nobreak >nul 2>&1
if exist awarenet.db del /f /q awarenet.db 2>nul
if exist awarenet.db-shm del /f /q awarenet.db-shm 2>nul
if exist awarenet.db-wal del /f /q awarenet.db-wal 2>nul
if exist campaigns.json del /f /q campaigns.json 2>nul
echo {}> campaigns.json

:: Captures
echo [*] Suppression captures...
if exist uploads rmdir /s /q uploads 2>nul
mkdir uploads 2>nul
if exist reports rmdir /s /q reports 2>nul
mkdir reports 2>nul
if exist campaign_media rmdir /s /q campaign_media 2>nul
mkdir campaign_media 2>nul
if exist campaign_audios rmdir /s /q campaign_audios 2>nul
mkdir campaign_audios 2>nul
if exist campaign_videos rmdir /s /q campaign_videos 2>nul
mkdir campaign_videos 2>nul
mkdir campaign_audios\_global 2>nul
mkdir campaign_videos\_global 2>nul
if exist downloads rmdir /s /q downloads 2>nul
mkdir downloads 2>nul
if exist custom_templates rmdir /s /q custom_templates 2>nul
mkdir custom_templates 2>nul

:: Licences/HWID
echo [*] Suppression licences...
if exist license.key del /f /q license.key 2>nul
if exist .hwid del /f /q .hwid 2>nul
if exist .license_activated del /f /q .license_activated 2>nul
if exist .build_config del /f /q .build_config 2>nul
:: AppData
if exist "%APPDATA%\AwareNet" rmdir /s /q "%APPDATA%\AwareNet" 2>nul

:: Build artefacts
echo [*] Suppression build...
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul
if exist __pycache__ rmdir /s /q __pycache__ 2>nul
if exist modules\__pycache__ rmdir /s /q modules\__pycache__ 2>nul
if exist tools\__pycache__ rmdir /s /q tools\__pycache__ 2>nul
if exist tests\__pycache__ rmdir /s /q tests\__pycache__ 2>nul
:: PyArmor
if exist dist_obf rmdir /s /q dist_obf 2>nul

:: Logs
del /f /q *.log 2>nul
del /f /q *.db-shm 2>nul
del /f /q *.db-wal 2>nul

:: Optionnel: .env perso -> garde le modele
echo [*] Nettoyage .env (garde modele)...
if exist .env (
  findstr /v "PANEL_PASSWORD PANEL_TOKEN" .env > .env.tmp 2>nul
  move /y .env.tmp .env >nul 2>&1
)

echo.
echo ============================================================
echo   Clean termine - outil tout neuf
echo   DB, captures, HWID, licences supprimes
echo   Prochaine execution generera nouveau HWID/DB
echo ============================================================
echo   Pour livrer: donne seulement le .exe (dist\*.exe)
echo   ou zippe le dossier SANS awarenet.db/uploads
echo ============================================================
pause
