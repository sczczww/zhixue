param([int]$Port = 8766, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
$runtimePath = Join-Path $projectPath 'var'
$baseUrl = "http://127.0.0.1:$Port"
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

function Test-ZhixueReady {
    try {
        $status = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 2
        return $status.service -eq 'zhixue'
    } catch { return $false }
}

if (Test-ZhixueReady) {
    Write-Host "Zhixue is running: $baseUrl"
    if (-not $NoBrowser) { Start-Process $baseUrl }
    exit 0
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is occupied by another service. No process was stopped."
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment is missing. Run start.bat first.'
}

$env:PYTHONPATH = ''
$env:PYTHONIOENCODING = 'utf-8'
$stdoutPath = Join-Path $runtimePath 'server.stdout.log'
$stderrPath = Join-Path $runtimePath 'server.stderr.log'
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-u', 'run.py', '--no-browser', '--port', "$Port") -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
@{ pid = $serverProcess.Id; startedAt = $serverProcess.StartTime.ToUniversalTime().ToString('o'); project = $projectPath; port = $Port } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimePath 'server-process.json') -Encoding UTF8

for ($attempt = 0; $attempt -lt 45; $attempt++) {
    if (Test-ZhixueReady) {
        Write-Host "Zhixue is running in the background: $baseUrl"
        Write-Host 'Use stop.bat to stop the local service.'
        if (-not $NoBrowser) { Start-Process $baseUrl }
        exit 0
    }
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Tail 20 }
        throw 'Zhixue exited during startup. Check var/server.stderr.log.'
    }
    Start-Sleep -Milliseconds 500
}
throw 'Startup did not complete in time. Check var/server.stderr.log.'
