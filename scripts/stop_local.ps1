$ErrorActionPreference = 'Stop'
$projectPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$statePath = Join-Path $projectPath 'var\server-process.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No managed service was recorded.'; exit 0 }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.project -ne $projectPath) { throw 'Recorded project path does not match.' }
$serverProcess = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if (-not $serverProcess) { Write-Host 'The service is already stopped.'; exit 0 }
$recordedStart = [DateTime]::Parse($state.startedAt).ToUniversalTime()
if ([Math]::Abs(($serverProcess.StartTime.ToUniversalTime() - $recordedStart).TotalSeconds) -gt 2) { throw 'Process identity changed. No process was stopped.' }
$expectedPython = Join-Path $projectPath '.venv\Scripts\python.exe'
$parentInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($state.pid)"
if ($parentInfo.ExecutablePath -ne $expectedPython -or $parentInfo.CommandLine -notmatch 'run\.py.*--no-browser') { throw 'Process command does not match. No process was stopped.' }
$children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($state.pid)"
foreach ($child in $children) {
    if ($child.Name -eq 'python.exe' -and $child.CommandLine -like "*$expectedPython*run.py*") {
        Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
    }
}
Stop-Process -Id $state.pid -ErrorAction SilentlyContinue
Write-Host 'Zhixue local service stopped. All data is preserved.'
