$ErrorActionPreference = "Stop"

function Get-EnvOrDefault {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Default
    )
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

function ConvertTo-RemoteSingleQuoted {
    param([Parameter(Mandatory=$true)][string]$Value)
    return "'" + ($Value -replace "'", "'\''") + "'"
}

function Get-AgentWatchProcess {
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'ForceHubAgent-Go.exe'" -ErrorAction SilentlyContinue
    return @($processes | Where-Object {
        $_.CommandLine -like "*--watch*" -and $_.CommandLine -like "*--post*"
    })
}

$SshHost = Get-EnvOrDefault -Name "FORCEHUB_SSH_HOST" -Default "ubuntu-vm"
$RemoteRepo = Get-EnvOrDefault -Name "FORCEHUB_REMOTE_REPO" -Default "/home/flozi/ForceHubProjects/forcehub-clean"
$AgentRoot = Get-EnvOrDefault -Name "FORCEHUB_AGENT_ROOT" -Default "D:\Scripts\ForceHubAgent"
$AgentExe = Get-EnvOrDefault -Name "FORCEHUB_AGENT_EXE" -Default "D:\Scripts\ForceHubAgent\ForceHubAgent-Go.exe"
$TokenFile = Get-EnvOrDefault -Name "FORCEHUB_AGENT_TOKEN_FILE" -Default "D:\Scripts\ForceHubAgent\agent_token.txt"
$CheckinUrl = Get-EnvOrDefault -Name "FORCEHUB_AGENT_CHECKIN_URL" -Default "http://127.0.0.1:18001/api/agents/checkin"

$startServer = Join-Path $PSScriptRoot "Start-ForceHubServer.ps1"
if (Test-Path $startServer) {
    Write-Host "Ensuring ForceHub server is started..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startServer
    if ($LASTEXITCODE -ne 0) {
        throw "ForceHub server start helper failed."
    }
}

$startTunnel = Join-Path $PSScriptRoot "Start-LocalIntegration.ps1"
if (Test-Path $startTunnel) {
    Write-Host "Ensuring local integration tunnel is started..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startTunnel
    if ($LASTEXITCODE -ne 0) {
        throw "Local integration start helper failed."
    }
}

if (!(Test-Path $AgentExe)) {
    throw "ForceHub Go agent executable not found: $AgentExe"
}

if ((Get-AgentWatchProcess).Count -gt 0) {
    Write-Host "ForceHub Go agent watch is already running."
    exit 0
}

Write-Host "Reading agent token from remote runtime file..."
$remoteRepoArg = ConvertTo-RemoteSingleQuoted -Value $RemoteRepo
$remoteCommand = "cd $remoteRepoArg && tr -d '\r\n' < data/agent_token.txt"
$token = & ssh $SshHost $remoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "Failed to read remote ForceHub agent token."
}

$tokenText = ($token -join "").Trim()
if ([string]::IsNullOrWhiteSpace($tokenText)) {
    throw "Remote ForceHub agent token is empty."
}

$tokenDir = Split-Path -Parent $TokenFile
if (!(Test-Path $tokenDir)) {
    New-Item -ItemType Directory -Path $tokenDir -Force | Out-Null
}
[System.IO.File]::WriteAllText($TokenFile, $tokenText, [System.Text.Encoding]::ASCII)

$logDir = Join-Path $AgentRoot "logs"
if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$outLog = Join-Path $logDir "forcehub-agent-go.out.log"
$errLog = Join-Path $logDir "forcehub-agent-go.err.log"

Write-Host "Starting ForceHub Go agent watch..."
$agentArgs = @(
    "--watch",
    "--post",
    "--interval", "3",
    "--server", $CheckinUrl,
    "--token-file", $TokenFile
)

Start-Process -FilePath $AgentExe -ArgumentList $agentArgs -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

Start-Sleep -Seconds 2

if ((Get-AgentWatchProcess).Count -eq 0) {
    throw "ForceHub Go agent watch did not stay running. Check logs in $logDir."
}

Write-Host "ForceHub Go agent watch is running."
