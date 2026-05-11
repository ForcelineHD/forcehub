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

$LocalPort = [int](Get-EnvOrDefault -Name "FORCEHUB_LOCAL_API_PORT" -Default "18001")

$connections = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($null -eq $connections) {
    Write-Host "No local integration tunnel is listening on 127.0.0.1:$LocalPort."
    exit 0
}

$processIds = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($processId in $processIds) {
    if ($processId -gt 0) {
        Write-Host "Stopping local integration tunnel process $processId..."
        Stop-Process -Id $processId -Force -ErrorAction Stop
    }
}

Write-Host "Local integration tunnel stopped."
