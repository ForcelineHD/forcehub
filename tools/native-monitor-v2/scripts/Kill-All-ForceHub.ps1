$ErrorActionPreference = "Stop"

function Invoke-HelperIfPresent {
    param([Parameter(Mandatory=$true)][string]$Name)

    $script = Join-Path $PSScriptRoot $Name
    if (Test-Path $script) {
        Write-Host "Running $Name..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed."
        }
    } else {
        Write-Host "Helper not found: $Name"
    }
}

Invoke-HelperIfPresent -Name "Stop-AgentWatch.ps1"
Invoke-HelperIfPresent -Name "Stop-LocalIntegration.ps1"
Invoke-HelperIfPresent -Name "Stop-ForceHubServer.ps1"

Write-Host "ForceHub local components stopped. Token files were not deleted."
