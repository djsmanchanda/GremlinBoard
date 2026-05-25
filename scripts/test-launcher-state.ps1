param()

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TrayScript = Join-Path $RepoRoot "scripts\gremlinboard-tray.ps1"
$TestRoot = Join-Path $RepoRoot "data\launcher-state-tests"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Equal {
    param(
        [object]$Actual,
        [object]$Expected,
        [string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

$env:GREMLINBOARD_TRAY_IMPORT_ONLY = "1"
. $TrayScript
Remove-Item Env:\GREMLINBOARD_TRAY_IMPORT_ONLY -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $TestRoot) {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null

$script:StateDir = $TestRoot
$script:StateFile = Join-Path $TestRoot "instances.json"

try {
    $oldState = @(
        [pscustomobject]@{
            id = "old-stable"
            mode = "stable"
            apiPid = 0
            webPid = 0
            apiPort = 2555
            webPort = 7555
            apiUrl = "http://127.0.0.1:2555/api"
            boardUrl = "http://127.0.0.1:7555"
            powerState = "active"
            startedAt = "2026-05-24T00:00:00.0000000Z"
        }
    )
    $oldState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    $loaded = @(Get-LauncherInstances)
    Assert-Equal $loaded.Count 1 "Old launcher state should load."
    Assert-Equal $loaded[0].state_version $LauncherStateVersion "Old launcher state should be versioned."
    Assert-Equal $loaded[0].apiLive $false "Missing apiLive should default false."
    Assert-Equal $loaded[0].runtimeState "active" "Missing runtimeState should derive from powerState."
    Assert-Equal $loaded[0].activeWidgetCount 0 "Missing activeWidgetCount should default zero."

    $partialState = @(
        [pscustomobject]@{
            mode = "dev"
            futureField = "kept out of canonical state but tolerated"
        },
        [pscustomobject]@{
            mode = "dev"
            futureField = "duplicate tolerated with generated id"
        }
    )
    $partialState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    $partial = @(Get-LauncherInstances)
    Assert-Equal $partial.Count 2 "Partial objects should normalize instead of being discarded."
    Assert-True ([string]::IsNullOrWhiteSpace($partial[0].id) -eq $false) "Partial object should receive an id."
    Assert-Equal $partial[0].apiLive $false "Partial object apiLive should default false."
    Assert-Equal $partial[0].runtimeState "unknown" "Partial object runtimeState should default unknown."

    $duplicateState = @(
        [pscustomobject]@{ id = "dupe"; mode = "stable"; apiPid = 0; webPid = 0 },
        [pscustomobject]@{ id = "dupe"; mode = "dev"; apiPid = 0; webPid = 0 }
    )
    $duplicateState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
    $deduped = @(Get-LauncherInstances)
    Assert-Equal $deduped.Count 1 "Duplicate launcher ids should be deduplicated."

    "{ invalid json" | Set-Content -LiteralPath $StateFile -Encoding UTF8
    $recovered = @(Get-LauncherInstances)
    Assert-Equal $recovered.Count 0 "Invalid JSON should recover to an empty canonical state."
    Assert-True ((Get-ChildItem -Path $TestRoot -Filter "instances.json.*.bak").Count -ge 1) "Invalid state should create a backup."
    Assert-True (Test-Path -LiteralPath (Join-Path $TestRoot "launcher-state.log")) "Recovery should write a visible state log."

    Save-LauncherInstances @($oldState)
    Assert-True (-not (Test-Path -LiteralPath "$StateFile.tmp")) "Atomic save should not leave a temp file."
    $saved = Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json
    Assert-Equal @($saved).Count 1 "Saved state should remain valid JSON."
    Assert-Equal @($saved)[0].state_version $LauncherStateVersion "Saved state should use the current version."

    Write-Host "launcher-state-tests: passed"
}
finally {
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
