[CmdletBinding()]
param(
    [int]$Port = 2558,
    [ValidateSet('claude', 'codex')]
    [string]$Provider = 'claude',
    [string]$Idea = 'Show the top 5 Hacker News stories with score and comment count, refreshed every 10 minutes.',
    [int]$TimeoutMinutes = 5
)

# Live-key end-to-end generation harness: isolated API + real provider key ->
# idea -> live generation job -> review gates -> approve -> install -> widget
# registered with a blueprint renderer. Exit codes: 0 success, 2 missing key,
# 3 approval blocked by review gates (a legitimate gate outcome), 1 harness failure.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $root 'apps/api'
$pythonExecutable = Join-Path $env:USERPROFILE 'micromamba\envs\gremlinboard\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'The gremlinboard Python 3.12 environment is required for the live generation harness.' }

$credentialProvider = if ($Provider -eq 'claude') { 'anthropic' } else { 'openai' }
$keyVariable = if ($Provider -eq 'claude') { 'GREMLINBOARD_E2E_ANTHROPIC_KEY' } else { 'GREMLINBOARD_E2E_OPENAI_KEY' }
$apiKey = [Environment]::GetEnvironmentVariable($keyVariable)
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    Write-Host "Set $keyVariable to a real $credentialProvider API key to run the live generation harness."
    exit 2
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gremlinboard-e2e-live-" + [guid]::NewGuid().ToString('N'))
$process = $null
$startedAt = Get-Date

function Write-Stage([string]$message) {
    $elapsed = ((Get-Date) - $startedAt).TotalSeconds
    Write-Host ("[{0,6:f1}s] {1}" -f $elapsed, $message)
}

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $databasePath = (Join-Path $tempRoot 'e2e-live.db').Replace('\', '/')
    $env:GREMLINBOARD_DATABASE_URL = "sqlite+aiosqlite:///$databasePath"
    $env:GREMLINBOARD_WIDGETS_DIR = Join-Path $tempRoot 'widgets'
    $env:GREMLINBOARD_API_HOST = '127.0.0.1'
    $env:GREMLINBOARD_API_PORT = "$Port"

    $process = Start-Process -FilePath $pythonExecutable -ArgumentList '-m', 'uvicorn', 'gremlinboard_api.main:app', '--host', '127.0.0.1', '--port', "$Port" -WorkingDirectory $apiRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $tempRoot 'api.out.log') -RedirectStandardError (Join-Path $tempRoot 'api.err.log')
    $base = "http://127.0.0.1:$Port"
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try { Invoke-WebRequest -UseBasicParsing "$base/api/health" | Out-Null; break } catch { Start-Sleep -Milliseconds 250 }
    }
    if ($attempt -eq 40) { throw "Timed out waiting for isolated API. See $tempRoot" }
    Write-Stage "isolated API up on port $Port"

    Invoke-RestMethod -Method Put -Uri "$base/api/system/credentials" -ContentType 'application/json' -Body (@{ provider = $credentialProvider; label = 'e2e live key'; value = $apiKey } | ConvertTo-Json) | Out-Null
    Write-Stage "$credentialProvider credential configured"

    $created = Invoke-RestMethod -Method Post -Uri "$base/api/ai/easy-generation/jobs" -ContentType 'application/json' -Body (@{ idea = $Idea; provider_id = $Provider } | ConvertTo-Json)
    $jobId = $created.job.id
    Write-Stage "generation job $jobId queued (provider $Provider)"

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $easy = $null
    while ($true) {
        Start-Sleep -Seconds 3
        $easy = Invoke-RestMethod -Uri "$base/api/ai/easy-generation/jobs/$jobId"
        $job = $easy.job
        Write-Stage ("job {0}% step={1} status={2}" -f $job.progress, $job.current_step, $job.status)
        if ($job.status -in @('completed', 'failed')) { break }
        if ((Get-Date) -gt $deadline) { throw "Generation did not finish within $TimeoutMinutes minutes." }
    }

    $job = $easy.job
    if ($job.status -ne 'completed') {
        throw "Generation job failed: $($job.error_message)"
    }
    if ($job.generation_mode -ne 'live') {
        throw "Job completed in '$($job.generation_mode)' mode, not 'live' - the credential did not reach the provider. Check api.err.log under $tempRoot"
    }
    if ($null -eq $easy.test_box) { throw 'Completed job has no test-box payload.' }
    $usage = if ($job.token_usage) { "$($job.token_usage.input_tokens) in / $($job.token_usage.output_tokens) out tokens" } else { 'no usage reported' }
    Write-Stage "live generation completed: model=$($job.model_id), $usage"

    try {
        $approved = Invoke-RestMethod -Method Post -Uri "$base/api/ai/generation/jobs/$jobId/approve" -ContentType 'application/json' -Body '{}'
    }
    catch {
        $detail = $null
        try { $detail = ($_.ErrorDetails.Message | ConvertFrom-Json).detail } catch {}
        Write-Host "Approval was blocked by review gates (legitimate gate outcome):"
        Write-Host ("  " + ($detail | Out-String).Trim())
        exit 3
    }
    Write-Stage "job approved (status $($approved.status))"

    $installed = Invoke-RestMethod -Method Post -Uri "$base/api/ai/generation/jobs/$jobId/install" -ContentType 'application/json' -Body '{}'
    Write-Stage "job installed (status $($installed.status))"

    $registry = Invoke-RestMethod -Uri "$base/api/registry/widgets"
    $widgetId = $job.widget_id
    $entry = $registry.$widgetId
    if ($null -eq $entry) { throw "Installed widget '$widgetId' not present in the registry." }
    if ($entry.manifest.renderer.kind -ne 'blueprint') { throw "Installed widget '$widgetId' renderer kind is '$($entry.manifest.renderer.kind)', expected 'blueprint'." }
    if ($null -eq $entry.blueprint) { throw "Installed widget '$widgetId' has no blueprint document in the registry payload." }
    Write-Stage "widget '$widgetId' registered with a blueprint renderer"

    Write-Host ''
    Write-Host 'LIVE E2E GENERATION PASSED'
    Write-Host ("  widget:          {0}" -f $widgetId)
    Write-Host ("  model:           {0}" -f $job.model_id)
    Write-Host ("  generation_mode: {0}" -f $job.generation_mode)
    Write-Host ("  tokens:          {0}" -f $usage)
    Write-Host ("  total time:      {0:f1}s" -f ((Get-Date) - $startedAt).TotalSeconds)
    exit 0
}
catch {
    Write-Host "HARNESS FAILURE: $_"
    $errLog = Join-Path $tempRoot 'api.err.log'
    if (Test-Path -LiteralPath $errLog) {
        Write-Host '--- api.err.log tail ---'
        Get-Content -LiteralPath $errLog -Tail 25 | ForEach-Object { Write-Host "  $_" }
    }
    exit 1
}
finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_WIDGETS_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_API_HOST -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_API_PORT -ErrorAction SilentlyContinue
}
