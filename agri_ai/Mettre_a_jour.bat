@echo off
setlocal
cd /d "%~dp0"
title Mise a jour des donnees agricoles

set "PYTHON=%~dp0.venv-py314\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo L'environnement Python du projet est introuvable.
    pause
    exit /b 1
)

"%PYTHON%" scripts\update_db.py --force
if errorlevel 1 (
    echo.
    echo Mise a jour incomplete. La base existante est conservee.
    echo Consultez data\update.log pour les details.
) else (
    echo.
    echo Mise a jour terminee.
)
pause
