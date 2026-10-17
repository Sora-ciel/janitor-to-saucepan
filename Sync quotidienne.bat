@echo off
REM Une synchronisation, sans ouvrir la fenetre de l'application.
REM Destine au Planificateur de taches de Windows.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Environnement Python absent. Lancez d'abord "Launch Naosnatcher.bat".
    exit /b 1
)

.venv\Scripts\python.exe -m naosnatcher.run %*
exit /b %errorlevel%
