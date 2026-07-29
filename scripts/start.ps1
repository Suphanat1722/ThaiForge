$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$requirementsStamp = Join-Path $venvPath ".requirements.sha256"
$frontendPath = Join-Path $projectRoot "frontend"
$packagePath = Join-Path $frontendPath "package.json"
$packageLockPath = Join-Path $frontendPath "package-lock.json"
$frontendStamp = Join-Path $frontendPath "node_modules\.thaiforge-package.sha256"
$envPath = Join-Path $projectRoot ".env"
$envExamplePath = Join-Path $projectRoot ".env.example"
$runPath = Join-Path $projectRoot "storage\run"
$pidPath = Join-Path $runPath "processes.json"

Set-Location $projectRoot

New-Item -ItemType Directory -Path $runPath -Force | Out-Null

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) {
        return
    }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

if (Test-Path -LiteralPath $pidPath) {
    try {
        $staleProcesses = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
        Stop-ProcessTree -ProcessId ([int]$staleProcesses.api)
        Stop-ProcessTree -ProcessId ([int]$staleProcesses.worker)
    } catch {
        Write-Host "Could not clean a stale PID file; continuing with a port check." -ForegroundColor Yellow
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

$existingListener = netstat.exe -ano -p tcp |
    Select-String '^\s*TCP\s+127\.0\.0\.1:8000\s+.*LISTENING\s+(\d+)\s*$' |
    Select-Object -First 1
if ($existingListener) {
    $existingPid = $existingListener.Matches[0].Groups[1].Value
    throw "Port 8000 is already used by process $existingPid. Close it, then run start.cmd again."
}

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $envExamplePath -Destination $envPath
    Write-Host "Created .env. Add GEMINI_API_KEY before generating a glossary." -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host "Preparing Python environment..." -ForegroundColor Cyan
    py -3.11 -m venv $venvPath
}

$requirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $requirementsStamp) {
    (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
} else {
    ""
}
if ($requirementsHash -ne $installedHash) {
    Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
    & $pythonPath -m pip install --disable-pip-version-check -r $requirementsPath
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
}

Write-Host "Preparing the web interface..." -ForegroundColor Cyan
Push-Location $frontendPath
try {
    $packageHash = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $packageLockPath) {
        $packageHash += ":" + (Get-FileHash -LiteralPath $packageLockPath -Algorithm SHA256).Hash
    }
    $installedPackageHash = if (Test-Path -LiteralPath $frontendStamp) {
        (Get-Content -LiteralPath $frontendStamp -Raw).Trim()
    } else {
        ""
    }
    if ($packageHash -ne $installedPackageHash) {
        & npm.cmd install --silent
        Set-Content -LiteralPath $frontendStamp -Value $packageHash -Encoding ASCII
    }
    & npm.cmd run build
} finally {
    Pop-Location
}

$apiArguments = @(
    "-m", "uvicorn", "backend.app.main:app",
    "--host", "127.0.0.1", "--port", "8000"
)
$workerArguments = @("-m", "backend.app.worker")

$apiProcess = $null
$workerProcess = $null
try {
    $workerProcess = Start-Process -FilePath $pythonPath -ArgumentList $workerArguments `
        -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList $apiArguments `
        -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden
    @{
        api = $apiProcess.Id
        worker = $workerProcess.Id
    } | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding ASCII

    $healthy = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($apiProcess.HasExited) {
            break
        }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" `
                -UseBasicParsing -TimeoutSec 1
            $health = $response.Content | ConvertFrom-Json
            if ($response.StatusCode -eq 200 -and $health.launcher_protocol -eq 2) {
                $healthy = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $healthy) {
        throw "API did not start. See storage\logs\api.log for details."
    }

    Write-Host ""
    Write-Host "ThaiForge V2 is ready at http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "You may close the browser; jobs continue while this window stays open." -ForegroundColor DarkGray
    Start-Process "http://127.0.0.1:8000"
    while (-not $apiProcess.HasExited) {
        Start-Sleep -Seconds 2
    }
    throw "ThaiForge API stopped unexpectedly. See storage\logs\api.log for details."
} finally {
    if ($workerProcess) {
        Stop-ProcessTree -ProcessId $workerProcess.Id
    }
    if ($apiProcess) {
        Stop-ProcessTree -ProcessId $apiProcess.Id
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}
