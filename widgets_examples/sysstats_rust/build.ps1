param(
    [string]$Configuration = "release"
)

$ErrorActionPreference = "Stop"

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BinDir = Join-Path $PackageRoot "bin"
$TargetName = if ($Configuration -eq "release") { "release" } else { "debug" }
$ExePath = Join-Path $PackageRoot "target\$TargetName\sysstats_rust.exe"
$OutPath = Join-Path $BinDir "sysstats_rust.exe"

Set-Location $PackageRoot

if ($Configuration -eq "release") {
    cargo build --release
} else {
    cargo build
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
Copy-Item -LiteralPath $ExePath -Destination $OutPath -Force
Write-Host "Copied $OutPath"