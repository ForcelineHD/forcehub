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

$SshHost = Get-EnvOrDefault -Name "FORCEHUB_SSH_HOST" -Default "ubuntu-vm"
$RemoteRepo = Get-EnvOrDefault -Name "FORCEHUB_REMOTE_REPO" -Default "/home/flozi/ForceHubProjects/forcehub-clean"

Write-Host "Starting ForceHub server..."

$remoteRepoArg = ConvertTo-RemoteSingleQuoted -Value $RemoteRepo
$remoteCommand = "cd $remoteRepoArg && scripts/forcehub.sh start && scripts/forcehub.sh status"

& ssh $SshHost $remoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start ForceHub server over SSH."
}

Write-Host "ForceHub server start requested."
