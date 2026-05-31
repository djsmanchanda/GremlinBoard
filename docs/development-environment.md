# Development Environment

GremlinBoard development uses a local micromamba environment for Python and the existing repository-local Node workflow for the Next.js frontend.

The canonical Python runtime is Python 3.12. Do not use Python 3.13 for backend validation.

## Requirements

- Micromamba
- Node.js installed outside micromamba
- npm from the installed Node distribution
- PowerShell on Windows

Do not install Node through conda or micromamba. Keep frontend dependencies in repository `node_modules`.

## Canonical Setup

From the repository root:

```powershell
.\scripts\bootstrap-dev.ps1
```

The bootstrap script:

- sets `MAMBA_ROOT_PREFIX` explicitly to avoid accidental `prefix = "y"` behavior.
- creates or updates the `gremlinboard` micromamba environment from `environment.yml`.
- installs the backend package in editable mode with `apps/api[dev]`.
- validates backend imports.
- runs `npm ci` when local frontend tooling is missing.
- validates TypeScript through `node_modules\.bin\tsc.cmd`.

The POSIX/Git Bash equivalent is:

```bash
./scripts/bootstrap-dev.sh
```

## Micromamba Layout

Expected Windows paths:

```text
MAMBA_ROOT_PREFIX=C:\Users\djsma\micromamba
micromamba.exe=C:\Users\djsma\AppData\Local\micromamba\micromamba.exe
environment=C:\Users\djsma\micromamba\envs\gremlinboard
```

If `micromamba info` reports `base environment : y`, the root prefix is not set for that shell. Set it explicitly before running micromamba:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" info
```

The bootstrap scripts set this variable themselves, so they do not depend on PowerShell profile initialization.

## Activation

Use `micromamba run` for deterministic one-off commands:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python --version
```

For an interactive PowerShell session:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
$env:MAMBA_EXE = "$env:LOCALAPPDATA\micromamba\micromamba.exe"
Import-Module "$env:MAMBA_ROOT_PREFIX\condabin\Mamba.psm1"
micromamba activate gremlinboard
```

## Editable Backend Install

`environment.yml` includes only the local editable package in the pip section:

```yaml
pip:
  - -e ./apps/api[dev]
```

To refresh the editable install:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pip install -e "apps/api[dev]"
```

## Backend Validation

Run all backend tests:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests -q -p no:langsmith
```

Run focused suites:

```powershell
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests\test_runtime_integration.py -q -p no:langsmith
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests\test_event_bus.py apps\api\tests\test_agent_registry.py -q -p no:langsmith
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests\test_cli.py apps\api\tests\test_control_plane.py -q -p no:langsmith
```

Run syntax compilation for touched backend files:

```powershell
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m py_compile apps\api\gremlinboard_api\main.py apps\api\gremlinboard_api\services\agent_registry.py
```

## Frontend Validation

Use local repository tooling:

```powershell
node_modules\.bin\tsc.cmd -p apps\web\tsconfig.json --noEmit
```

Run the Playwright smoke suite with managed local servers:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
$env:GREMLINBOARD_E2E_API_PYTHON_COMMAND = "`"$env:LOCALAPPDATA\micromamba\micromamba.exe`" run -n gremlinboard python"
$env:PLAYWRIGHT_START_WEBSERVER = "1"
node_modules\.bin\playwright.cmd test -c apps\web\playwright.config.ts tests\smoke
```

If frontend dependencies need a clean install, stop any running GremlinBoard/Next.js process first because Next native SWC binaries can be locked on Windows. Then run:

```powershell
$env:NPM_CONFIG_PREFIX = "C:\Program Files\nodejs"
npm ci
node_modules\.bin\tsc.cmd -p apps\web\tsconfig.json --noEmit
```

If the global npm launcher is still broken, bypass it:

```powershell
node "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" ci
```

## Running Locally

Development API:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard uvicorn --app-dir apps/api gremlinboard_api.main:app --reload --reload-dir apps/api --reload-dir widgets --reload-exclude node_modules --reload-exclude data --reload-exclude .git --host 127.0.0.1 --port 2556 --no-access-log
```

Development web:

```powershell
$env:NPM_CONFIG_PREFIX = "C:\Program Files\nodejs"
npm run dev:web
```

Stable utility mode still uses the launchers:

```powershell
.\Start-GremlinBoard.bat
.\Stop-GremlinBoard.bat
```

## Launcher State Compatibility

The tray launcher persists managed API/web process records in `data\launcher\instances.json`. That file is treated as an operator-state cache, not as a database. On every load, `scripts\gremlinboard-tray.ps1` normalizes records to the current `state_version`, fills missing runtime fields with safe defaults, deduplicates malformed duplicates, and rewrites the file atomically.

If the launcher finds invalid or truncated JSON, it writes a timestamped `.bak` copy next to `instances.json`, records a visible event in `data\launcher\launcher-state.log`, and rebuilds a clean empty state. Operators should not need to delete `instances.json` manually after schema changes.

Run the focused launcher persistence smoke checks:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-launcher-state.ps1
```

## Migration From `.venv`

The old `.venv` workflow is no longer the canonical path, but it should remain untouched until a micromamba setup has passed validation.

Previous known-good validation was:

```powershell
.\.venv\Scripts\python.exe -m pytest apps\api\tests -q -p no:langsmith
```

After micromamba validation passes, prefer:

```powershell
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests -q -p no:langsmith
```

## Troubleshooting

### Micromamba reports `y`

Symptom:

```text
base environment : y
envs directories : y\envs
```

Fix:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" info
```

Do not patch the PowerShell profile unless you intentionally want automatic shell activation. The bootstrap scripts do not require profile changes.

### `pydantic_core` import fails

Symptom:

```text
ImportError: DLL load failed while importing _pydantic_core: Access is denied.
```

Fix:

```powershell
$env:MAMBA_ROOT_PREFIX = "$env:USERPROFILE\micromamba"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python --version
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pip install -e "apps/api[dev]"
& "$env:LOCALAPPDATA\micromamba\micromamba.exe" run -n gremlinboard python -m pytest apps\api\tests -q -p no:langsmith
```

### Global npm is broken

Symptom:

```text
Cannot find module 'C:\Users\djsma\AppData\Roaming\npm\node_modules\npm\bin\npm-cli.js'
```

Fix for the current shell:

```powershell
$env:NPM_CONFIG_PREFIX = "C:\Program Files\nodejs"
npm --version
```

If that still fails:

```powershell
node "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" --version
node "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js" ci
```

### `npm ci` cannot unlink Next SWC

Symptom:

```text
EPERM: operation not permitted, unlink 'node_modules\@next\swc-win32-x64-msvc\next-swc.win32-x64-msvc.node'
```

Fix:

```powershell
.\Stop-GremlinBoard.bat
Get-Process node -ErrorAction SilentlyContinue
$env:NPM_CONFIG_PREFIX = "C:\Program Files\nodejs"
npm ci
```

If a GremlinBoard `next start -p 7555` child remains after the launcher exits, stop that process before retrying.

### Global pytest plugins interfere

Use `-p no:langsmith` for backend test commands. This keeps unrelated global pytest plugins from affecting local Pydantic imports.
