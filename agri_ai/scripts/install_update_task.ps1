$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv-py314\Scripts\python.exe"
$updater = Join-Path $projectRoot "scripts\update_db.py"
$taskName = "MulimoAgriAiQuarterlyDatabaseUpdate"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python project environment not found: $python"
}
if (-not (Test-Path -LiteralPath $updater -PathType Leaf)) {
    throw "Database updater not found: $updater"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$updater`"" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At "9:00AM"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Actualise les données agricoles locales au plus une fois tous les 90 jours." `
    -Force | Out-Null

Write-Host "Tâche installée : $taskName"
Write-Host "Elle vérifie chaque jour à 09:00 si une mise à jour trimestrielle est due."
Write-Host "La mise à jour ne démarre que si Windows détecte une connexion réseau."
