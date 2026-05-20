[CmdletBinding()]
param(
    [string] $EnvName = "gremlinboard",
    [string] $MambaRootPrefix = "$env:USERPROFILE\micromamba",
    [string] $MicromambaExe = "$env:LOCALAPPDATA\micromamba\micromamba.exe",
    [switch] $SkipFrontend,
    [switch] $SkipNpmCi
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvironmentFile = Join-Path $RepoRoot "environment.yml"

if (-not (Test-Path -LiteralPath $MicromambaExe)) {
    $command = Get-Command micromamba -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "micromamba was not found. Install micromamba or pass -MicromambaExe."
    }
    $MicromambaExe = $command.Source
}

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "environment.yml was not found at $EnvironmentFile"
}

$env:MAMBA_ROOT_PREFIX = $MambaRootPrefix
Write-Host "micromamba: $MicromambaExe"
Write-Host "MAMBA_ROOT_PREFIX: $env:MAMBA_ROOT_PREFIX"

$envList = & $MicromambaExe env list
$ExpectedPrefix = Join-Path $MambaRootPrefix "envs\$EnvName"
$envExists = [bool]($envList | Where-Object { $_ -match [regex]::Escape($ExpectedPrefix) })
if ($envExists) {
    & $MicromambaExe install -n $EnvName --override-channels -c conda-forge -f $EnvironmentFile -y
} else {
    & $MicromambaExe create -n $EnvName --override-channels -c conda-forge -f $EnvironmentFile -y
}

& $MicromambaExe run -n $EnvName python -m pip install -e "apps/api[dev]"
& $MicromambaExe run -n $EnvName python -c "import sys, fastapi, pydantic, sqlalchemy, gremlinboard_api; print(sys.executable); print(sys.version); print('backend-imports-ok')"

if (-not $SkipFrontend) {
    $npmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "Node.js was not found on PATH. Install Node outside micromamba."
    }
    if (Test-Path -LiteralPath $npmCli) {
        $env:NPM_CONFIG_PREFIX = "C:\Program Files\nodejs"
    }

    $tsc = Join-Path $RepoRoot "node_modules\.bin\tsc.cmd"
    if (-not $SkipNpmCi -and -not (Test-Path -LiteralPath $tsc)) {
        if (Test-Path -LiteralPath $npmCli) {
            & node $npmCli ci
        } else {
            & npm ci
        }
    }

    if (-not (Test-Path -LiteralPath $tsc)) {
        throw "Local TypeScript compiler was not found. Run npm ci after stopping any running Next.js process."
    }
    & $tsc -p (Join-Path $RepoRoot "apps\web\tsconfig.json") --noEmit
}

Write-Host "GremlinBoard development environment is ready."
Write-Host "Activate with: $MicromambaExe activate $EnvName"
Write-Host "Or run commands with: $MicromambaExe run -n $EnvName <command>"
