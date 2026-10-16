$ErrorActionPreference = 'Stop'
$taskRoot = 'C:\Users\grant\harnessExperiment'
$taskOut = Join-Path $taskRoot 'experiments\session_harness\c019_runs'
$taskPython = Join-Path $taskRoot '.runtime\test-venv\Scripts\python.exe'
$taskDriver = Join-Path $taskRoot 'experiments\session_harness\run_codex_mini.py'
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-u', $taskDriver, '--execute', '--parallel-pilot') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskOut 'campaign.stdout.txt') -RedirectStandardError (Join-Path $taskOut 'campaign.stderr.txt') -PassThru
$taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskOut 'campaign.pid.txt')
Write-Output "Started card 019 background runner: PID $($taskProcess.Id)"
