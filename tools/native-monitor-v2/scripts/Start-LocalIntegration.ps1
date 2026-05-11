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

function Test-LocalListener {
    param([Parameter(Mandatory=$true)][int]$Port)
    $listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $listener
}

$SshHost = Get-EnvOrDefault -Name "FORCEHUB_SSH_HOST" -Default "ubuntu-vm"
$LocalPort = [int](Get-EnvOrDefault -Name "FORCEHUB_LOCAL_API_PORT" -Default "18001")
$RemotePort = [int](Get-EnvOrDefault -Name "FORCEHUB_REMOTE_API_PORT" -Default "8001")

if (Test-LocalListener -Port $LocalPort) {
    Write-Host "Local integration tunnel already listening on 127.0.0.1:$LocalPort."
    exit 0
}

Write-Host "Starting local integration tunnel on 127.0.0.1:$LocalPort..."

$sshArgs = @(
    "-o", "ExitOnForwardFailure=yes",
    "-N",
    "-L", "127.0.0.1:$LocalPort`:127.0.0.1:$RemotePort",
    $SshHost
)

Start-Process -FilePath "ssh.exe" -ArgumentList $sshArgs -WindowStyle Minimized

Start-Sleep -Seconds 2

if (!(Test-LocalListener -Port $LocalPort)) {
    throw "Local integration tunnel did not start on 127.0.0.1:$LocalPort."
}

Write-Host "Local integration tunnel is listening on 127.0.0.1:$LocalPort."
