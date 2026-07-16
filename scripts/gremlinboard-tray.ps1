param(
    [ValidateSet("stable", "dev")]
    [string]$Mode = "stable",
    [switch]$StopAll,
    [ValidateSet("stable", "dev")]
    [string]$StopMode,
    [switch]$List
)

$ErrorActionPreference = "Stop"

# In tray mode, hide the hosting console window so launching from a .bat or a
# plain `powershell -File` never leaves a blank terminal behind for the tray's
# lifetime. CLI modes (-StopAll/-StopMode/-List) keep their console output.
if (-not $StopAll -and -not $StopMode -and -not $List) {
    try {
        $consoleApi = Add-Type -Name "ConsoleHider" -Namespace "GremlinBoardTray" -PassThru -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@
        $consoleWindow = $consoleApi::GetConsoleWindow()
        if ($consoleWindow -ne [IntPtr]::Zero) {
            [void]$consoleApi::ShowWindow($consoleWindow, 0)
        }
    }
    catch {
        # Cosmetic only; never block tray startup on console-hiding.
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DataDir = if ($env:GREMLINBOARD_DATA_DIR) { $env:GREMLINBOARD_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "GremlinBoard" }
$StateDir = Join-Path $DataDir "launcher"
$StateFile = Join-Path $StateDir "instances.json"
$LauncherStateVersion = 2

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

# One-time migration: if the platform launcher state directory is empty, carry
# over any legacy repo-local launcher state so running instances aren't lost.
$LegacyStateFile = Join-Path $RepoRoot "data\launcher\instances.json"
if (-not (Test-Path -LiteralPath $StateFile) -and (Test-Path -LiteralPath $LegacyStateFile)) {
    try {
        Copy-Item -LiteralPath $LegacyStateFile -Destination $StateFile -Force
    }
    catch {
        # Non-fatal: the launcher just starts with empty state if this fails.
    }
}

function Write-LauncherStateEvent {
    param(
        [string]$Event,
        [string]$Message
    )

    $line = "{0} {1} {2}" -f (Get-Date).ToString("o"), $Event, $Message
    $logPath = Join-Path $StateDir "launcher-state.log"
    try {
        Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    }
    catch {
        Write-Warning $line
    }
}

function Quote-PSLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Test-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    return $null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]
}

function Get-ObjectProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Default = $null
    )

    if (Test-ObjectProperty -Object $Object -Name $Name) {
        $value = $Object.PSObject.Properties[$Name].Value
        if ($null -ne $value) {
            return $value
        }
    }
    return $Default
}

function ConvertTo-StringValue {
    param(
        [object]$Value,
        [string]$Default = ""
    )

    if ($null -eq $Value) {
        return $Default
    }
    return [string]$Value
}

function ConvertTo-NullableStringValue {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }
    return [string]$Value
}

function ConvertTo-IntValue {
    param(
        [object]$Value,
        [int]$Default = 0
    )

    if ($null -eq $Value) {
        return $Default
    }
    try {
        return [int]$Value
    }
    catch {
        return $Default
    }
}

function ConvertTo-BoolValue {
    param(
        [object]$Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) {
        return $Default
    }
    if ($Value -is [bool]) {
        return $Value
    }
    $text = ([string]$Value).Trim()
    if ($text -match "^(true|1|yes)$") {
        return $true
    }
    if ($text -match "^(false|0|no)$") {
        return $false
    }
    return $Default
}

function Add-WinUiTrayMenuRenderer {
    if ("GremlinBoard.WinUiTrayRenderer" -as [type]) {
        return
    }

    Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @"
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace GremlinBoard {
    public sealed class WinUiTrayColorTable : ProfessionalColorTable {
        private readonly Color Background = Color.FromArgb(32, 32, 32);
        private readonly Color Selected = Color.FromArgb(58, 58, 58);
        private readonly Color Border = Color.FromArgb(68, 68, 68);

        public override Color ToolStripDropDownBackground { get { return Background; } }
        public override Color ImageMarginGradientBegin { get { return Background; } }
        public override Color ImageMarginGradientMiddle { get { return Background; } }
        public override Color ImageMarginGradientEnd { get { return Background; } }
        public override Color MenuBorder { get { return Border; } }
        public override Color MenuItemBorder { get { return Selected; } }
        public override Color MenuItemSelected { get { return Selected; } }
        public override Color SeparatorDark { get { return Color.FromArgb(74, 74, 74); } }
        public override Color SeparatorLight { get { return Color.FromArgb(74, 74, 74); } }
    }

    public sealed class WinUiTrayRenderer : ToolStripProfessionalRenderer {
        private readonly Color Background = Color.FromArgb(32, 32, 32);
        private readonly Color Selected = Color.FromArgb(58, 58, 58);
        private readonly Color Border = Color.FromArgb(68, 68, 68);
        private readonly Color Text = Color.FromArgb(243, 243, 243);
        private readonly Color Muted = Color.FromArgb(166, 166, 166);

        public WinUiTrayRenderer() : base(new WinUiTrayColorTable()) {
            RoundedEdges = false;
        }

        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e) {
            using (SolidBrush brush = new SolidBrush(Background)) {
                e.Graphics.FillRectangle(brush, e.AffectedBounds);
            }
        }

        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) {
            using (Pen pen = new Pen(Border)) {
                Rectangle bounds = new Rectangle(Point.Empty, new Size(e.ToolStrip.Width - 1, e.ToolStrip.Height - 1));
                e.Graphics.DrawRectangle(pen, bounds);
            }
        }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) {
            Rectangle bounds = new Rectangle(Point.Empty, e.Item.Size);
            Color fill = e.Item.Selected && e.Item.Enabled ? Selected : Background;
            using (SolidBrush brush = new SolidBrush(fill)) {
                e.Graphics.FillRectangle(brush, bounds);
            }
        }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e) {
            e.TextColor = e.Item.Enabled ? Text : Muted;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e) {
            int y = e.Item.Height / 2;
            using (Pen pen = new Pen(Border)) {
                e.Graphics.DrawLine(pen, 12, y, e.Item.Width - 12, y);
            }
        }
    }
}
"@
}

function New-GremlinBoardTrayIcon {
    $bitmap = New-Object System.Drawing.Bitmap 64, 64
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $background = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Rectangle 0, 0, 64, 64),
        [System.Drawing.Color]::FromArgb(24, 24, 24),
        [System.Drawing.Color]::FromArgb(39, 39, 39),
        [System.Drawing.Drawing2D.LinearGradientMode]::ForwardDiagonal
    )
    $panelBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(246, 246, 246))
    $screenBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(222, 252, 237))
    $accentBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(76, 194, 122))
    $dimBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(143, 171, 184))
    $borderPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(78, 78, 78)), 2
    $panelPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(171, 181, 190)), 2

    try {
        $graphics.FillEllipse($background, 4, 4, 56, 56)
        $graphics.DrawEllipse($borderPen, 4, 4, 56, 56)
        $graphics.FillRectangle($panelBrush, 16, 18, 32, 27)
        $graphics.DrawRectangle($panelPen, 16, 18, 32, 27)
        $graphics.FillRectangle($screenBrush, 20, 22, 15, 19)
        $graphics.FillRectangle($dimBrush, 38, 22, 6, 19)
        $graphics.FillRectangle($accentBrush, 22, 24, 11, 4)
        $graphics.FillRectangle($accentBrush, 22, 31, 11, 4)
        $graphics.FillRectangle($accentBrush, 22, 38, 11, 3)
    }
    finally {
        $background.Dispose()
        $panelBrush.Dispose()
        $screenBrush.Dispose()
        $accentBrush.Dispose()
        $dimBrush.Dispose()
        $borderPen.Dispose()
        $panelPen.Dispose()
        $graphics.Dispose()
    }

    $handle = $bitmap.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($handle).Clone()
    $bitmap.Dispose()
    return $icon
}

function Set-WinUiTrayMenuItemStyle {
    param([System.Windows.Forms.ToolStripItem]$Item)

    $Item.ForeColor = [System.Drawing.Color]::FromArgb(243, 243, 243)
    $Item.BackColor = [System.Drawing.Color]::FromArgb(32, 32, 32)
    $Item.Padding = New-Object System.Windows.Forms.Padding 10, 3, 14, 3
    $Item.Margin = New-Object System.Windows.Forms.Padding 0, 1, 0, 1
}

function Update-TrayStatusText {
    param(
        [object]$Instance,
        [System.Windows.Forms.ToolStripMenuItem]$StatusItem,
        [System.Windows.Forms.NotifyIcon]$Notify
    )

    $StatusItem.Text = "Status  API $($Instance.apiLive)  Web $($Instance.webLive)  Runtime $($Instance.powerState)  Widgets $($Instance.activeWidgetCount)  Errors $($Instance.recentErrorCount)"
    $Notify.Text = "GremlinBoard $($Instance.mode) - $($Instance.powerState)"
}

function Normalize-LauncherInstance {
    param([object]$Instance)

    if ($null -eq $Instance -or $Instance -isnot [psobject]) {
        return $null
    }

    $apiPort = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "apiPort") -Default 0
    $webPort = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "webPort") -Default 0
    $apiUrl = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "apiUrl") -Default $(if ($apiPort -gt 0) { "http://127.0.0.1:$apiPort/api" } else { "" })
    $boardUrl = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "boardUrl") -Default $(if ($webPort -gt 0) { "http://127.0.0.1:$webPort" } else { "" })
    $runtimeState = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "runtimeState" -Default (Get-ObjectProperty -Object $Instance -Name "powerState" -Default "unknown")) -Default "unknown"

    return [pscustomobject][ordered]@{
        state_version = $LauncherStateVersion
        id = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "id") -Default ([guid]::NewGuid().ToString())
        mode = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "mode") -Default "stable"
        apiPid = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "apiPid") -Default 0
        webPid = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "webPid") -Default 0
        apiPort = $apiPort
        webPort = $webPort
        apiUrl = $apiUrl
        boardUrl = $boardUrl
        systemUrl = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "systemUrl") -Default $(if ($boardUrl) { "$boardUrl/system" } else { "" })
        apiLog = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "apiLog")
        apiErrorLog = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "apiErrorLog")
        webLog = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "webLog")
        webErrorLog = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "webErrorLog")
        apiLive = ConvertTo-BoolValue -Value (Get-ObjectProperty -Object $Instance -Name "apiLive") -Default $false
        webLive = ConvertTo-BoolValue -Value (Get-ObjectProperty -Object $Instance -Name "webLive") -Default $false
        powerState = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "powerState" -Default $runtimeState) -Default "unknown"
        runtimeState = $runtimeState
        activeWidgetCount = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "activeWidgetCount") -Default 0
        recentErrorCount = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "recentErrorCount") -Default 0
        websocketSubscribers = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "websocketSubscribers") -Default 0
        monitorCadenceSeconds = ConvertTo-IntValue -Value (Get-ObjectProperty -Object $Instance -Name "monitorCadenceSeconds") -Default 0
        lastStartupError = ConvertTo-NullableStringValue -Value (Get-ObjectProperty -Object $Instance -Name "lastStartupError")
        repoRoot = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "repoRoot") -Default $RepoRoot
        startedAt = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "startedAt") -Default (Get-Date).ToString("o")
        updatedAt = ConvertTo-StringValue -Value (Get-ObjectProperty -Object $Instance -Name "updatedAt") -Default (Get-Date).ToString("o")
    }
}

function Normalize-LauncherState {
    param([object[]]$Instances)

    $normalized = @()
    $seenIds = @{}
    foreach ($instance in @($Instances)) {
        $next = Normalize-LauncherInstance -Instance $instance
        if ($null -eq $next) {
            Write-LauncherStateEvent -Event "launcher.state_invalid" -Message "Dropped malformed launcher instance during normalization."
            continue
        }
        if ($seenIds.ContainsKey($next.id)) {
            Write-LauncherStateEvent -Event "launcher.state_invalid" -Message "Dropped duplicate launcher instance id '$($next.id)'."
            continue
        }
        $seenIds[$next.id] = $true
        $normalized += $next
    }
    return @($normalized)
}

function Backup-LauncherStateFile {
    param([string]$Reason)

    if (-not (Test-Path -LiteralPath $StateFile)) {
        return
    }
    $backupPath = "{0}.{1}.bak" -f $StateFile, (Get-Date -Format "yyyyMMdd-HHmmss")
    try {
        Copy-Item -LiteralPath $StateFile -Destination $backupPath -Force
        Write-LauncherStateEvent -Event $Reason -Message "Backed up launcher state to $backupPath."
    }
    catch {
        Write-LauncherStateEvent -Event $Reason -Message "Could not back up launcher state: $($_.Exception.Message)"
    }
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
        Backup-LauncherStateFile -Reason "launcher.state_invalid"
        Write-LauncherStateEvent -Event "launcher.state_recovered" -Message "Launcher state was unreadable. Rebuilding clean state."
        Save-LauncherInstances @()
        return @()
    }

    if ($null -eq $items) {
        return @()
    }

    $loaded = @($items)
    $normalized = @(Normalize-LauncherState -Instances $loaded)
    if (($normalized | ConvertTo-Json -Depth 8 -Compress) -ne ($loaded | ConvertTo-Json -Depth 8 -Compress)) {
        Write-LauncherStateEvent -Event "launcher.state_normalized" -Message "Normalized launcher state from persisted schema to version $LauncherStateVersion."
        Save-LauncherInstances $normalized
    }
    return @($normalized)
}

function Save-LauncherInstances {
    param([object[]]$Instances)
    $normalized = @(Normalize-LauncherState -Instances @($Instances))
    $tempPath = "$StateFile.tmp"
    $json = if ($normalized.Count -eq 0) { "[]" } else { ConvertTo-Json -InputObject @($normalized) -Depth 8 }
    $json | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $StateFile -Force
}

function Test-ProcessAlive {
    param([object]$PidValue)
    if ($null -eq $PidValue) {
        return $false
    }

    try {
        $processId = [int]$PidValue
        if ($processId -le 0) {
            return $false
        }
        [void](Get-Process -Id $processId -ErrorAction Stop)
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

function Stop-LauncherInstancesByMode {
    param([ValidateSet("stable", "dev")][string]$SelectedMode)

    $instances = @(Get-CleanLauncherInstances)
    $matching = @($instances | Where-Object { $_.mode -eq $SelectedMode })
    foreach ($instance in $matching) {
        Stop-LauncherInstance $instance
    }
    Save-LauncherInstances @($instances | Where-Object { $_.mode -ne $SelectedMode })
    Write-Host "Stopped $($matching.Count) managed GremlinBoard $SelectedMode instance(s)."
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

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    return [pscustomobject]@{
        Process = $process
        Stdout = $stdout
        Stderr = $stderr
    }
}

function Test-HttpEndpoint {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        return $false
    }
}

function Get-RuntimeStatusSnapshot {
    param(
        [object]$Instance,
        [bool]$Passive = $true
    )

    $snapshot = [ordered]@{
        powerState = "unknown"
        activeWidgetCount = 0
        recentErrorCount = 0
        websocketSubscribers = 0
        monitorCadenceSeconds = 0
    }

    try {
        $headers = @{
            "x-gremlin-presence-source" = "tray"
        }
        if ($Passive) {
            $headers["x-gremlin-presence-passive"] = "true"
        }
        $status = Invoke-RestMethod -Uri "$($Instance.apiUrl)/runtime/status" -Headers $headers -TimeoutSec 2 -ErrorAction Stop
        $snapshot.powerState = [string]$status.state
        $snapshot.activeWidgetCount = [int]$status.active_runners
        $snapshot.websocketSubscribers = [int]$status.websocket_subscribers
        $snapshot.monitorCadenceSeconds = [int]$status.monitor_cadence_seconds
        $snapshot.recentErrorCount = @($status.provider_degradation).Count
    }
    catch {
        $snapshot.powerState = "unreachable"
    }

    return $snapshot
}

function Update-LauncherInstanceStatus {
    param(
        [object]$Instance,
        [bool]$Passive = $true
    )

    $Instance.apiLive = (Test-ProcessAlive $Instance.apiPid) -and (Test-HttpEndpoint "$($Instance.apiUrl)/health")
    $Instance.webLive = (Test-ProcessAlive $Instance.webPid) -and (Test-HttpEndpoint $Instance.boardUrl)
    $snapshot = Get-RuntimeStatusSnapshot -Instance $Instance -Passive $Passive
    $Instance.powerState = $snapshot.powerState
    $Instance.runtimeState = $snapshot.powerState
    $Instance.activeWidgetCount = $snapshot.activeWidgetCount
    $Instance.recentErrorCount = $snapshot.recentErrorCount
    $Instance.websocketSubscribers = $snapshot.websocketSubscribers
    $Instance.monitorCadenceSeconds = $snapshot.monitorCadenceSeconds
    $Instance.updatedAt = (Get-Date).ToString("o")
    return $Instance
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

    if (-not (Test-ProcessAlive $apiProcess.Process.Id) -or -not (Test-ProcessAlive $webProcess.Process.Id)) {
        foreach ($startedPid in @($apiProcess.Process.Id, $webProcess.Process.Id)) {
            if (Test-ProcessAlive $startedPid) {
                Stop-Process -Id $startedPid -Force -ErrorAction SilentlyContinue
            }
        }

        $startupError = "GremlinBoard startup failed because API or web exited immediately. Check logs in $StateDir."
        $failedInstance = [pscustomobject]@{
            state_version = $LauncherStateVersion
            id = [guid]::NewGuid().ToString()
            mode = $SelectedMode
            apiPid = $apiProcess.Process.Id
            webPid = $webProcess.Process.Id
            apiPort = $apiPort
            webPort = $webPort
            apiUrl = "http://127.0.0.1:$apiPort/api"
            boardUrl = "http://127.0.0.1:$webPort"
            systemUrl = "http://127.0.0.1:$webPort/system"
            apiLog = $apiProcess.Stdout
            apiErrorLog = $apiProcess.Stderr
            webLog = $webProcess.Stdout
            webErrorLog = $webProcess.Stderr
            apiLive = $false
            webLive = $false
            powerState = "failed"
            runtimeState = "failed"
            activeWidgetCount = 0
            recentErrorCount = 0
            websocketSubscribers = 0
            monitorCadenceSeconds = 0
            lastStartupError = $startupError
            repoRoot = $RepoRoot
            startedAt = (Get-Date).ToString("o")
            updatedAt = (Get-Date).ToString("o")
        }
        Save-LauncherInstances @((Get-LauncherInstances) + $failedInstance)
        throw $startupError
    }

    $instance = [pscustomobject]@{
        state_version = $LauncherStateVersion
        id = [guid]::NewGuid().ToString()
        mode = $SelectedMode
        apiPid = $apiProcess.Process.Id
        webPid = $webProcess.Process.Id
        apiPort = $apiPort
        webPort = $webPort
        apiUrl = "http://127.0.0.1:$apiPort/api"
        boardUrl = "http://127.0.0.1:$webPort"
        systemUrl = "http://127.0.0.1:$webPort/system"
        apiLog = $apiProcess.Stdout
        apiErrorLog = $apiProcess.Stderr
        webLog = $webProcess.Stdout
        webErrorLog = $webProcess.Stderr
        apiLive = $false
        webLive = $false
        powerState = "starting"
        runtimeState = "starting"
        activeWidgetCount = 0
        recentErrorCount = 0
        websocketSubscribers = 0
        monitorCadenceSeconds = 0
        lastStartupError = $null
        repoRoot = $RepoRoot
        startedAt = (Get-Date).ToString("o")
        updatedAt = (Get-Date).ToString("o")
    }

    $instance = Update-LauncherInstanceStatus $instance

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
    Add-WinUiTrayMenuRenderer
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Text = "GremlinBoard $($Instance.mode) - $($Instance.boardUrl)"
    $trayIcon = New-GremlinBoardTrayIcon
    $notify.Icon = $trayIcon
    $notify.Visible = $true

    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    $menu.Renderer = New-Object GremlinBoard.WinUiTrayRenderer
    $menu.BackColor = [System.Drawing.Color]::FromArgb(32, 32, 32)
    $menu.ForeColor = [System.Drawing.Color]::FromArgb(243, 243, 243)
    $menu.Font = New-Object System.Drawing.Font "Segoe UI", 10
    $menu.ShowImageMargin = $false
    $menu.ShowCheckMargin = $false
    $menu.Padding = New-Object System.Windows.Forms.Padding 8, 8, 8, 8
    $openBoard = New-Object System.Windows.Forms.ToolStripMenuItem("Open Board")
    $openSystem = New-Object System.Windows.Forms.ToolStripMenuItem("Open System Panel")
    $statusItem = New-Object System.Windows.Forms.ToolStripMenuItem("Status: starting")
    $statusItem.Enabled = $false
    $openLogs = New-Object System.Windows.Forms.ToolStripMenuItem("Open Launcher Logs")
    $refreshStatus = New-Object System.Windows.Forms.ToolStripMenuItem("Refresh Status")
    $separator = New-Object System.Windows.Forms.ToolStripSeparator
    $stopExit = New-Object System.Windows.Forms.ToolStripMenuItem("Stop Services and Exit")

    foreach ($item in @($openBoard, $openSystem, $statusItem, $openLogs, $refreshStatus, $stopExit)) {
        Set-WinUiTrayMenuItemStyle -Item $item
    }
    $statusItem.ForeColor = [System.Drawing.Color]::FromArgb(166, 166, 166)
    $stopExit.ForeColor = [System.Drawing.Color]::FromArgb(255, 153, 164)
    $separator.BackColor = [System.Drawing.Color]::FromArgb(32, 32, 32)
    $separator.ForeColor = [System.Drawing.Color]::FromArgb(74, 74, 74)

    $openBoard.add_Click({ Start-Process $Instance.boardUrl })
    $openSystem.add_Click({ Start-Process $Instance.systemUrl })
    $openLogs.add_Click({ Start-Process explorer.exe $StateDir })
    $refreshStatus.add_Click({
        Update-LauncherInstanceStatus -Instance $Instance -Passive $false | Out-Null
        Save-LauncherInstances @(Get-LauncherInstances | ForEach-Object { if ($_.id -eq $Instance.id) { $Instance } else { $_ } })
        Update-TrayStatusText -Instance $Instance -StatusItem $statusItem -Notify $notify
    })
    $stopExit.add_Click({
        Stop-LauncherInstance $Instance
        Remove-LauncherInstance $Instance.id
        $notify.Visible = $false
        $notify.Dispose()
        $trayIcon.Dispose()
        [System.Windows.Forms.Application]::Exit()
    })

    [void]$menu.Items.Add($openBoard)
    [void]$menu.Items.Add($openSystem)
    [void]$menu.Items.Add($statusItem)
    [void]$menu.Items.Add($refreshStatus)
    [void]$menu.Items.Add($openLogs)
    [void]$menu.Items.Add($separator)
    [void]$menu.Items.Add($stopExit)
    $notify.ContextMenuStrip = $menu
    $notify.add_DoubleClick({ Start-Process $Instance.boardUrl })
    $notify.ShowBalloonTip(2000, "GremlinBoard", "Running $($Instance.mode) on $($Instance.boardUrl)", [System.Windows.Forms.ToolTipIcon]::Info)

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 15000
    $timer.add_Tick({
        Update-LauncherInstanceStatus -Instance $Instance -Passive $true | Out-Null
        Save-LauncherInstances @(Get-LauncherInstances | ForEach-Object { if ($_.id -eq $Instance.id) { $Instance } else { $_ } })
        Update-TrayStatusText -Instance $Instance -StatusItem $statusItem -Notify $notify
    })
    $timer.Start()
    $refreshStatus.PerformClick()

    try {
        [System.Windows.Forms.Application]::Run()
    }
    finally {
        $timer.Stop()
        $timer.Dispose()
        $notify.Visible = $false
        $notify.Dispose()
        $trayIcon.Dispose()
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

if ($StopMode) {
    Stop-LauncherInstancesByMode -SelectedMode $StopMode
    exit 0
}

if ($List) {
    Show-Instances @(Get-CleanLauncherInstances)
    exit 0
}

if ($env:GREMLINBOARD_TRAY_IMPORT_ONLY -eq "1") {
    return
}

if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne "STA") {
    throw "The tray launcher must run with PowerShell -STA. Use Start-GremlinBoard.bat or Start-GremlinBoard-Dev.bat."
}

Enforce-InstanceLimit
$startedInstance = Start-GremlinBoardStack -SelectedMode $Mode
Start-Tray -Instance $startedInstance
