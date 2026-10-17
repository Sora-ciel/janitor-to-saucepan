@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Premiere installation : creation de l'environnement Python...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Python introuvable. Installez Python 3.11+ depuis python.org
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERREUR] Installation des dependances echouee.
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe -m naosnatcher
if errorlevel 1 pause
