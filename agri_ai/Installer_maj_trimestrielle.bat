@echo off
setlocal
cd /d "%~dp0"
title Installation - mise a jour trimestrielle des donnees

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_update_task.ps1"
if errorlevel 1 (
    echo.
    echo L'installation de la tache planifiee a echoue.
    pause
    exit /b 1
)

echo.
echo Installation terminee. La base locale reste utilisable hors ligne.
pause
