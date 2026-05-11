$ErrorActionPreference = "Stop"

$processes = Get-CimInstance Win32_Process -Filter "Name = 'ForceHubAgent-Go.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*--watch*" }

if ($null -eq $processes) {
    Write-Host "No ForceHub Go agent watch process is running."
    exit 0
}

foreach ($process in @($processes)) {
    Write-Host "Stopping ForceHub Go agent watch process $($process.ProcessId)..."
    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
}

Write-Host "ForceHub Go agent watch stopped."
