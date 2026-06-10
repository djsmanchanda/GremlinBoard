param(
    [ValidateSet("stable", "dev")]
    [string]$Mode = "stable",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TrayScript = Join-Path $RepoRoot "scripts\gremlinboard-tray.ps1"
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "GremlinBoard.lnk"
$PowerShellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path -LiteralPath $TrayScript)) {
    throw "GremlinBoard tray launcher was not found at $TrayScript"
}

if (-not (Test-Path -LiteralPath $PowerShellPath)) {
    $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop
    $PowerShellPath = $powerShellCommand.Source
}

if ($Remove) {
    if (Test-Path -LiteralPath $ShortcutPath) {
        Remove-Item -LiteralPath $ShortcutPath -Force
        Write-Host "Removed GremlinBoard autostart shortcut: $ShortcutPath"
    }
    else {
        Write-Host "GremlinBoard autostart shortcut was not installed."
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PowerShellPath
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File `"$TrayScript`" -Mode $Mode"
$shortcut.WorkingDirectory = $RepoRoot
$shortcut.Description = "Start GremlinBoard $Mode tray launcher at Windows logon"
$shortcut.WindowStyle = 7
$shortcut.IconLocation = "$PowerShellPath,0"
$shortcut.Save()

Write-Host "Installed GremlinBoard $Mode autostart shortcut: $ShortcutPath"
