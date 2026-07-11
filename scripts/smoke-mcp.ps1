[CmdletBinding()]
param(
    [int]$Port = 2557
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gremlinboard-mcp-smoke-" + [guid]::NewGuid().ToString('N'))
$apiRoot = Join-Path $root 'apps/api'
$pythonExecutable = Join-Path $env:USERPROFILE 'micromamba\envs\gremlinboard\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'The gremlinboard Python 3.12 environment is required for the MCP smoke test.' }
$token = [guid]::NewGuid().ToString('N')
$process = $null

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $databasePath = (Join-Path $tempRoot 'mcp-smoke.db').Replace('\', '/')
    $env:GREMLINBOARD_DATABASE_URL = "sqlite+aiosqlite:///$databasePath"
    $env:GREMLINBOARD_WIDGETS_DIR = Join-Path $tempRoot 'widgets'
    $env:GREMLINBOARD_API_HOST = '127.0.0.1'
    $env:GREMLINBOARD_API_PORT = "$Port"

    $process = Start-Process -FilePath $pythonExecutable -ArgumentList '-m', 'uvicorn', 'gremlinboard_api.main:app', '--host', '127.0.0.1', '--port', "$Port" -WorkingDirectory $apiRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $tempRoot 'api.out.log') -RedirectStandardError (Join-Path $tempRoot 'api.err.log')
    $healthUrl = "http://127.0.0.1:$Port/api/health"
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try { Invoke-WebRequest -UseBasicParsing $healthUrl | Out-Null; break } catch { Start-Sleep -Milliseconds 250 }
    }
    if ($attempt -eq 40) { throw "Timed out waiting for isolated API. See $tempRoot" }

    Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:$Port/api/system/credentials" -ContentType 'application/json' -Body (@{ provider = 'mcp'; label = 'smoke token'; value = $token } | ConvertTo-Json) | Out-Null

    $env:MCP_SMOKE_URL = "http://127.0.0.1:$Port/mcp/"
    $env:MCP_SMOKE_TOKEN = $token
    $python = @(
        'import asyncio',
        'import os',
        'import httpx',
        'from mcp import ClientSession',
        'from mcp.client.streamable_http import streamable_http_client',
        '',
        'async def main() -> None:',
        '    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {os.environ[''MCP_SMOKE_TOKEN'']}"}) as client:',
        '        async with streamable_http_client(os.environ["MCP_SMOKE_URL"], http_client=client) as (read, write, _):',
        '            async with ClientSession(read, write) as session:',
        '                await session.initialize()',
        '                names = {tool.name for tool in (await session.list_tools()).tools}',
        '                assert {"gremlinboard_runtime_status", "widgets.generate", "generation.install"}.issubset(names)',
        '                generated = await session.call_tool("widgets.generate", {"idea": "Create an offline smoke-test status widget."})',
        '                job_id = generated.structuredContent["job"]["id"]',
        '                blocked = await session.call_tool("generation.install", {"job_id": job_id})',
        '                assert blocked.isError',
        '',
        'asyncio.run(main())'
    ) -join [Environment]::NewLine
    $python | & $pythonExecutable -
    if ($LASTEXITCODE -ne 0) { throw 'MCP client validation failed.' }
    Write-Host 'MCP smoke passed with an isolated API database.'
}
finally {
    if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_WIDGETS_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_API_HOST -ErrorAction SilentlyContinue
    Remove-Item Env:GREMLINBOARD_API_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:MCP_SMOKE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:MCP_SMOKE_TOKEN -ErrorAction SilentlyContinue
}
