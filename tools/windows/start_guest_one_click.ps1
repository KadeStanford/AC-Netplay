param(
    [string]$HostIP = "127.0.0.1",
    [string]$RoomName = "TestRoom01",
    [string]$PlayerName = "GuestPlayer01",
    [int]$Port = 9000,
    [string]$InstallDir = "$env:USERPROFILE\AC-Netplay",
    [string]$RepoUrl = "https://github.com/KadeStanford/AC-Netplay.git",
    [bool]$AutoInstallGeckoCodes = $true,
    [string]$DolphinUserPath = ""
)

$ErrorActionPreference = "Stop"

try {

$Host.UI.RawUI.WindowTitle = "AC-Netplay Guest"

function Test-RepoRoot([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path "pyproject.toml")) -and
           (Test-Path (Join-Path $Path "server\server.py")) -and
           (Test-Path (Join-Path $Path "client\client.py"))
}

function Ensure-Repo([string]$TargetDir, [string]$GitRepoUrl) {
    if (Test-RepoRoot $TargetDir) {
        Write-Host "Using existing AC-Netplay repo at $TargetDir" -ForegroundColor Cyan
        return $TargetDir
    }

    if (-not (Test-Path $TargetDir)) {
        New-Item -ItemType Directory -Path $TargetDir | Out-Null
    }

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "Cloning AC-Netplay into $TargetDir ..." -ForegroundColor Cyan
        & git clone --depth 1 $GitRepoUrl $TargetDir
        return $TargetDir
    }

    Write-Host "git not found. Downloading ZIP archive instead..." -ForegroundColor Yellow
    $zipUrl = "https://codeload.github.com/KadeStanford/AC-Netplay/zip/refs/heads/main"
    $tempRoot = Join-Path $env:TEMP ("ac-netplay-bootstrap-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "ac-netplay.zip"
    $extractPath = Join-Path $tempRoot "extract"

    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    New-Item -ItemType Directory -Path $extractPath | Out-Null

    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

    $sourceRoot = Join-Path $extractPath "AC-Netplay-main"
    if (-not (Test-Path $sourceRoot)) {
        throw "Could not find extracted AC-Netplay-main folder."
    }

    Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $TargetDir -Recurse -Force
    return $TargetDir
}

function Resolve-RepoRoot() {
    $scriptRepoCandidate = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    if (Test-RepoRoot $scriptRepoCandidate) {
        return $scriptRepoCandidate
    }

    $cwdCandidate = (Get-Location).Path
    if (Test-RepoRoot $cwdCandidate) {
        return $cwdCandidate
    }

    return (Ensure-Repo -TargetDir $InstallDir -GitRepoUrl $RepoUrl)
}

$repoRoot = Resolve-RepoRoot
$clientDir = Join-Path $repoRoot "client"
$clientVenv = Join-Path $clientDir ".venv"

if ($AutoInstallGeckoCodes) {
    $geckoInstaller = Join-Path $repoRoot "tools\windows\install_gecko_codes.ps1"
    if (Test-Path $geckoInstaller) {
        & $geckoInstaller -RepoRoot $repoRoot -DolphinUserPath $DolphinUserPath
    }
    else {
        Write-Host "Gecko installer script not found at $geckoInstaller" -ForegroundColor Yellow
    }
}

$pythonCmd = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

if (-not (Test-Path (Join-Path $clientVenv "Scripts\python.exe"))) {
    & $pythonCmd -m venv $clientVenv
}

$clientPython = Join-Path $clientVenv "Scripts\python.exe"
& $clientPython -m pip install -r (Join-Path $clientDir "requirements.txt")

$serverUrl = "ws://$HostIP`:$Port"

Write-Host "Starting guest client for $serverUrl in room '$RoomName' ..." -ForegroundColor Green
    & $clientPython (Join-Path $clientDir "client.py") --server $serverUrl --room $RoomName --name $PlayerName
}
catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host ""
}
finally {}
