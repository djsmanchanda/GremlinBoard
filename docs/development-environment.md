# Development Environment

GremlinBoard backend development uses Python 3.12 in a project-local virtual environment.

Do not use a global Python 3.13 interpreter for backend tests. Some Windows installs can fail importing `pydantic_core` from Python 3.13 with `ImportError: DLL load failed while importing _pydantic_core: Access is denied`.

## Requirements

- Python 3.12
- Node.js 20+
- npm
- PowerShell on Windows

## Windows Setup

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
npm install
```

Use this interpreter for backend work:

```powershell
.\.venv\Scripts\python.exe
```

## Editable Install

The API package is installed from `apps/api/pyproject.toml`.

```powershell
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
```

This installs FastAPI, SQLAlchemy, Pydantic, Uvicorn, pytest, pytest-asyncio, Ruff, and the `gremlinboard` console script.

## Test Commands

Run all backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest apps\api\tests -q -p no:langsmith
```

Run the runtime integration suite:

```powershell
.\.venv\Scripts\python.exe -m pytest apps\api\tests\test_runtime_integration.py -q -p no:langsmith
```

Run a focused runtime status test:

```powershell
.\.venv\Scripts\python.exe -m pytest apps\api\tests\test_runtime_integration.py::test_runtime_status_reports_control_plane_snapshot -q -p no:langsmith
```

Run syntax compilation for touched backend files:

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\api\gremlinboard_api\main.py apps\api\gremlinboard_api\runtime\manager.py
```

## Running Locally

Development API:

```powershell
npm run dev:api
```

Development web:

```powershell
npm run dev:web
```

Stable utility mode still uses the Windows launchers:

```powershell
.\Start-GremlinBoard.bat
.\Stop-GremlinBoard.bat
```

## Troubleshooting

### `pydantic_core` import fails

Symptom:

```text
ImportError: DLL load failed while importing _pydantic_core: Access is denied.
```

Fix:

1. Confirm you are not using global Python 3.13:

   ```powershell
   .\.venv\Scripts\python.exe --version
   ```

2. Reinstall the editable backend package inside the venv:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install --force-reinstall -e "apps/api[dev]"
   ```

3. Re-run pytest through the venv interpreter:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest apps\api\tests -q -p no:langsmith
   ```

### Global pytest plugins interfere

Use `-p no:langsmith` for backend test commands. This keeps unrelated global pytest plugins from affecting local Pydantic imports.

### `pytest` is missing

Install dev dependencies through the editable package:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
```

### `uvicorn` is missing

Install the API package:

```powershell
.\.venv\Scripts\python.exe -m pip install -e "apps/api[dev]"
```
