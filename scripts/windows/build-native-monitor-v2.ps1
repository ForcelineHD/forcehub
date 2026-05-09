$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\Scripts\ForceHubAgent\ForceHubNativeMonitorV2"
$PublishDir = Join-Path $ProjectRoot "publish"

Write-Host "=== ForceHub Native Monitor V2 Build ==="

if (!(Test-Path $ProjectRoot)) {
    throw "Project not found: $ProjectRoot"
}

cd $ProjectRoot

Get-Process ForceHubNativeMonitorV2 -ErrorAction SilentlyContinue | Stop-Process -Force

Remove-Item ".\bin",".\obj",$PublishDir -Recurse -Force -ErrorAction SilentlyContinue

dotnet build

dotnet publish -c Release -r win-x64 --self-contained false -o $PublishDir

$Exe = Join-Path $PublishDir "ForceHubNativeMonitorV2.exe"

if (!(Test-Path $Exe)) {
    throw "Publish failed. EXE not found: $Exe"
}

Write-Host "Built:"
Get-Item $Exe | Select-Object FullName,Length,LastWriteTime | Format-List

Start-Process $Exe
