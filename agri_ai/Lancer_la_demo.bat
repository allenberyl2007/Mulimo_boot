@echo off
setlocal
cd /d "%~dp0"
title Demonstration - Conseil agricole RDC

set "PYTHON=%~dp0.venv-py314\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Python 3.14 et son environnement du projet sont introuvables.
    echo Reinstallez les dependances en suivant README.md, puis relancez ce fichier.
    pause
    exit /b 1
)

if not exist "data\simulation.db" (
    echo La base de donnees data\simulation.db est introuvable.
    echo Verifiez que le projet est complet avant la demonstration.
    pause
    exit /b 1
)

"%PYTHON%" -c "import numpy, pandas, scipy, sklearn, onnxruntime" >nul 2>nul
if errorlevel 1 (
    echo Des dependances Python du projet sont manquantes.
    echo Reinstallez-les avec : uv pip install --python .venv-py314\Scripts\python.exe -r requirements.txt
    pause
    exit /b 1
)

echo Demarrage de la demonstration...
echo Le navigateur va s'ouvrir automatiquement a l'adresse locale affichee par le serveur.
echo Si le port 8000 est deja utilise, un autre port sera choisi.
echo Gardez cette fenetre ouverte. Pour arreter, appuyez sur Ctrl+C.
echo.

"%PYTHON%" app.py

if errorlevel 1 (
    echo.
    echo Le serveur s'est arrete avec une erreur.
    echo Si le port 8000 est deja utilise, fermez l'autre demonstration et reessayez.
    pause
)
