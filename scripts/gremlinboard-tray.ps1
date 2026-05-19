param(
    [ValidateSet("stable", "dev")]
    [string]$Mode = "stable",
    [switch]$StopAll,
    [switch]$List
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $RepoRoot "data\launcher"
$StateFile = Join-Path $StateDir "instances.json"

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Quote-PSLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-LauncherInstances {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return @()
    }

    $raw = Get-Content -Raw -LiteralPath $StateFile
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @()
    }

    try {
        $items = $raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Launcher state was unreadable. Resetting $StateFile."
        return @()
    }

    if ($null -eq $items) {
        return @()
    }

    return @($items)
}

function Save-LauncherInstances {
    param([object[]]$Instances)
    if ($null -eq $Instances -or $Instances.Count -eq 0) {
        "[]" | Set-Content -LiteralPath $StateFile -Encoding UTF8
        return
    }

    ConvertTo-Json -InputObject @($Instances) -Depth 8 | Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Test-ProcessAlive {
    param([object]$PidValue)
    if ($null -eq $PidValue) {
        return $false
    }

    try {
        [void](Get-Process -Id ([int]$PidValue) -ErrorAction Stop)
        return $true
    }
    catch {
        return $false
    }
}

function Get-CleanLauncherInstances {
    $instances = @(Get-LauncherInstances)
    $alive = @()

    foreach ($instance in $instances) {
        if ((Test-ProcessAlive $instance.apiPid) -or (Test-ProcessAlive $instance.webPid)) {
            $alive += $instance
        }
    }

    Save-LauncherInstances $alive
    return @($alive)
}

function Stop-LauncherInstance {
    param([object]$Instance)

    foreach ($pidValue in @($Instance.webPid, $Instance.apiPid)) {
        if (Test-ProcessAlive $pidValue) {
            try {
                Stop-Process -Id ([int]$pidValue) -Force -ErrorAction Stop
            }
            catch {
                Write-Warning "Could not stop process ${pidValue}: $($_.Exception.Message)"
            }
        }
    }
}

function Remove-LauncherInstance {
    param([string]$InstanceId)
    $remaining = @(Get-LauncherInstances | Where-Object { $_.id -ne $InstanceId })
    Save-LauncherInstances $remaining
}

function Show-Instances {
    param([object[]]$Instances)

    if ($Instances.Count -eq 0) {
        Write-Host "No managed GremlinBoard instances are running."
        return
    }

    for ($index = 0; $index -lt $Instances.Count; $index++) {
        $instance = $Instances[$index]
        $number = $index + 1
        Write-Host ("[{0}] {1} board={2} apiPid={3} webPid={4} started={5}" -f $number, $instance.mode, $instance.boardUrl, $instance.apiPid, $instance.webPid, $instance.startedAt)
    }
}

function Resolve-NodeExe {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -eq $node) {
        throw "node.exe was not found on PATH. Install Node.js 20+ or start from a shell where node is available."
    }

    return $node.Source
}

function Get-PythonRunner {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        & $py.Source -3.12 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3.12"
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return "python"
    }

    throw "Python was not found on PATH. Install Python 3.12+ with the API dependencies."
}

function Test-TcpPortOpen {
    param([int]$Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $result.AsyncWaitHandle.WaitOne(200, $false)
        if ($connected) {
            $client.EndConnect($result)
            return $true
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Ensure-StableWebBuild {
    param(
        [string]$NodeExe,
        [int]$ApiPort
    )

    $buildIdPath = Join-Path $RepoRoot "apps\web\.next\BUILD_ID"
    if (Test-Path -LiteralPath $buildIdPath) {
        return
    }

    Write-Host "Production web build is missing. Building apps/web once before starting utility mode..."
    Push-Location (Join-Path $RepoRoot "apps\web")
    try {
        $previousApiUrl = $env:NEXT_PUBLIC_GREMLINBOARD_API_URL
        $env:NEXT_PUBLIC_GREMLINBOARD_API_URL = "http://127.0.0.1:$ApiPort/api"
        & $NodeExe "..\..\node_modules\next\dist\bin\next" build
        if ($LASTEXITCODE -ne 0) {
            throw "Next production build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        $env:NEXT_PUBLIC_GREMLINBOARD_API_URL = $previousApiUrl
        Pop-Location
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$Command,
        [string]$WorkingDirectory
    )

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdout = Join-Path $StateDir "$timestamp-$Name.log"
    $stderr = Join-Path $StateDir "$timestamp-$Name.err.log"

    return Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
}

function Start-GremlinBoardStack {
    param([string]$SelectedMode)

    $apiPort = 2555
    $webPort = 7555
    if ($SelectedMode -eq "dev") {
        $apiPort = 2556
        $webPort = 7556
    }

    $trackedPorts = @(Get-CleanLauncherInstances | ForEach-Object { $_.apiPort; $_.webPort })
    foreach ($port in @($apiPort, $webPort)) {
        if ((Test-TcpPortOpen $port) -and ($trackedPorts -notcontains $port)) {
            throw "Port $port is already in use by an unmanaged process. Stop that process or use the other launcher mode."
        }
    }

    $nodeExe = Resolve-NodeExe
    $pythonRunner = Get-PythonRunner

    if ($SelectedMode -eq "stable") {
        Ensure-StableWebBuild -NodeExe $nodeExe -ApiPort $apiPort
    }

    $apiFlags = "--app-dir apps/api gremlinboard_api.main:app --host 127.0.0.1 --port $apiPort --no-access-log"
    if ($SelectedMode -eq "dev") {
        $apiFlags = "--app-dir apps/api gremlinboard_api.main:app --reload --reload-dir apps/api --reload-dir widgets --reload-exclude node_modules --reload-exclude data --reload-exclude .git --reload-exclude .pytest-backend --host 127.0.0.1 --port $apiPort --no-access-log"
    }

    $apiPythonPath = "$RepoRoot;$(Join-Path $RepoRoot "apps\api")"
    $apiCommand = "`$env:PYTHONPATH = $(Quote-PSLiteral $apiPythonPath); $pythonRunner -m uvicorn $apiFlags"
    $webCommand = "`$env:NEXT_PUBLIC_GREMLINBOARD_API_URL = $(Quote-PSLiteral "http://127.0.0.1:$apiPort/api"); & $(Quote-PSLiteral $nodeExe) $(Quote-PSLiteral "..\..\node_modules\next\dist\bin\next") start -p $webPort"

    if ($SelectedMode -eq "dev") {
        $webCommand = "`$env:NEXT_PUBLIC_GREMLINBOARD_API_URL = $(Quote-PSLiteral "http://127.0.0.1:$apiPort/api"); & $(Quote-PSLiteral $nodeExe) $(Quote-PSLiteral "..\..\node_modules\next\dist\bin\next") dev -p $webPort"
    }

    $apiProcess = Start-ManagedProcess -Name "$SelectedMode-api" -Command $apiCommand -WorkingDirectory $RepoRoot
    Start-Sleep -Seconds 1
    $webProcess = Start-ManagedProcess -Name "$SelectedMode-web" -Command $webCommand -WorkingDirectory (Join-Path $RepoRoot "apps\web")
    Start-Sleep -Seconds 2

    if (-not (Test-ProcessAlive $apiProcess.Id) -or -not (Test-ProcessAlive $webProcess.Id)) {
        foreach ($startedPid in @($apiProcess.Id, $webProcess.Id)) {
            if (Test-ProcessAlive $startedPid) {
                Stop-Process -Id $startedPid -Force -ErrorAction SilentlyContinue
            }
        }

        throw "GremlinBoard startup failed because API or web exited immediately. Check logs in $StateDir."
    }

    $instance = [pscustomobject]@{
        id = [guid]::NewGuid().ToString()
        mode = $SelectedMode
        apiPid = $apiProcess.Id
        webPid = $webProcess.Id
        apiPort = $apiPort
        webPort = $webPort
        boardUrl = "http://127.0.0.1:$webPort"
        systemUrl = "http://127.0.0.1:$webPort/system"
        repoRoot = $RepoRoot
        startedAt = (Get-Date).ToString("o")
    }

    $instances = @(Get-CleanLauncherInstances)
    Save-LauncherInstances @($instances + $instance)
    return $instance
}

function Enforce-InstanceLimit {
    $instances = @(Get-CleanLauncherInstances)
    $sameMode = @($instances | Where-Object { $_.mode -eq $Mode })

    if ($sameMode.Count -gt 0) {
        Write-Host "A managed GremlinBoard $Mode instance is already running."
        Show-Instances $sameMode
        $choice = Read-Host "Enter R to restart it, O to open it, or C to cancel"

        if ($choice -match "^[Oo]$") {
            Start-Process $sameMode[0].boardUrl
            exit 0
        }

        if ($choice -notmatch "^[Rr]$") {
            exit 0
        }

        foreach ($instance in $sameMode) {
            Stop-LauncherInstance $instance
            Remove-LauncherInstance $instance.id
        }

        $instances = @(Get-CleanLauncherInstances)
    }

    while ($instances.Count -ge 2) {
        Write-Host "GremlinBoard allows at most two managed stacks: one stable and one dev."
        Show-Instances $instances
        $choice = Read-Host "Enter the number to terminate before starting $Mode, or C to cancel"

        if ($choice -match "^[Cc]$") {
            exit 0
        }

        $index = 0
        if ([int]::TryParse($choice, [ref]$index) -and $index -ge 1 -and $index -le $instances.Count) {
            $selected = $instances[$index - 1]
            Stop-LauncherInstance $selected
            Remove-LauncherInstance $selected.id
            $instances = @(Get-CleanLauncherInstances)
        }
        else {
            Write-Host "Invalid selection."
        }
    }
}

function Start-Tray {
    param([object]$Instance)

    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Text = "GremlinBoard $($Instance.mode) - $($Instance.boardUrl)"
    $notify.Icon = [System.Drawing.SystemIcons]::Application
    $notify.Visible = $true

    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $openBoard = New-Object System.Windows.Forms.ToolStripMenuItem("Open Board")
    $openSystem = New-Object System.Windows.Forms.ToolStripMenuItem("Open System Panel")
    $separator = New-Object System.Windows.Forms.ToolStripSeparator
    $stopExit = New-Object System.Windows.Forms.ToolStripMenuItem("Stop Services and Exit")

    $openBoard.add_Click({ Start-Process $Instance.boardUrl })
    $openSystem.add_Click({ Start-Process $Instance.systemUrl })
    $stopExit.add_Click({
        Stop-LauncherInstance $Instance
        Remove-LauncherInstance $Instance.id
        $notify.Visible = $false
        $notify.Dispose()
        [System.Windows.Forms.Application]::Exit()
    })

    [void]$menu.Items.Add($openBoard)
    [void]$menu.Items.Add($openSystem)
    [void]$menu.Items.Add($separator)
    [void]$menu.Items.Add($stopExit)
    $notify.ContextMenuStrip = $menu
    $notify.add_DoubleClick({ Start-Process $Instance.boardUrl })
    $notify.ShowBalloonTip(2000, "GremlinBoard", "Running $($Instance.mode) on $($Instance.boardUrl)", [System.Windows.Forms.ToolTipIcon]::Info)

    try {
        [System.Windows.Forms.Application]::Run()
    }
    finally {
        $notify.Visible = $false
        $notify.Dispose()
    }
}

if ($StopAll) {
    $instances = @(Get-CleanLauncherInstances)
    foreach ($instance in $instances) {
        Stop-LauncherInstance $instance
    }
    Save-LauncherInstances @()
    Write-Host "Stopped $($instances.Count) managed GremlinBoard instance(s)."
    exit 0
}

if ($List) {
    Show-Instances @(Get-CleanLauncherInstances)
    exit 0
}

if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne "STA") {
    throw "The tray launcher must run with PowerShell -STA. Use Start-GremlinBoard.bat or Start-GremlinBoard-Dev.bat."
}

Enforce-InstanceLimit
$startedInstance = Start-GremlinBoardStack -SelectedMode $Mode
Start-Tray -Instance $startedInstance
