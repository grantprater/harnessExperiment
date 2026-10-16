$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot '.runtime\test-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw "Reticle interpreter not found: $taskPython"
}
$taskBin = Join-Path $env:USERPROFILE '.local\bin'
New-Item -ItemType Directory -Force -Path $taskBin | Out-Null
$taskLauncher = Join-Path $taskBin 'reticle.cmd'
if (Test-Path -LiteralPath $taskLauncher) {
    $taskExisting = Get-Content -LiteralPath $taskLauncher -Raw
    if (-not $taskExisting.Contains('Reticle harness launcher')) {
        throw "An unrelated reticle command already exists: $taskLauncher"
    }
}
# Keep the caller's working directory; PYTHONPATH loads this checkout from anywhere.
$taskContent = @"
@echo off
rem Reticle harness launcher
setlocal
set "PYTHONPATH=$taskRoot"
"$taskPython" -m reticle %*
exit /b %errorlevel%
"@
Set-Content -LiteralPath $taskLauncher -Value $taskContent -Encoding ascii
$taskUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$taskEntries = @($taskUserPath -split ';' | Where-Object { $_ })
if ($taskEntries -notcontains $taskBin) {
    [Environment]::SetEnvironmentVariable('Path', (($taskEntries + $taskBin) -join ';'), 'User')
}
Write-Output "Installed $taskLauncher. Open a new terminal and run reticle."
