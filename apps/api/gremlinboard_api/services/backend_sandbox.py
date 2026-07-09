from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


async def dry_run_backend(
    source: str,
    manifest: dict[str, Any],
    config: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Run generated backend start()+get_state() in an isolated subprocess."""

    config_payload = config or {}
    temp_root = _sandbox_temp_root()
    with tempfile.TemporaryDirectory(prefix="gremlinboard-backend-dryrun-", dir=str(temp_root), ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        package_root = tmp_path / "widgets" / str(manifest["id"])
        package_root.mkdir(parents=True)
        (tmp_path / "widgets" / "__init__.py").write_text('"""Dry-run widgets."""\n', encoding="utf-8")
        (package_root / "__init__.py").write_text('"""Dry-run widget package."""\n', encoding="utf-8")
        (package_root / "backend.py").write_text(source, encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        config_path = tmp_path / "config.json"
        runner_path = tmp_path / "runner.py"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        config_path.write_text(json.dumps(config_payload), encoding="utf-8")
        api_root = Path(__file__).resolve().parents[2]
        runner_path.write_text(_runner_source(), encoding="utf-8")

        return await asyncio.to_thread(
            _run_backend_subprocess,
            [
                sys.executable,
                "-I",
                str(runner_path),
                str(tmp_path),
                str(api_root),
                str(manifest_path),
                str(config_path),
            ],
            timeout,
        )



def _run_backend_subprocess(argv: list[str], timeout: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"backend dry-run timed out after {timeout:g}s"}

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {"ok": False, "error": stderr_text or stdout_text or f"backend dry-run exited {completed.returncode}"}
    try:
        result = json.loads(stdout_text or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "backend dry-run returned invalid JSON"}
    if stderr_text and isinstance(result, dict):
        result.setdefault("stderr", stderr_text)
    return result if isinstance(result, dict) else {"ok": False, "error": "backend dry-run returned non-object JSON"}


def _sandbox_temp_root() -> Path:
    root = Path("C:/tmp")
    if root.exists():
        return root
    fallback = Path.cwd() / "data" / "tmp"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _runner_source() -> str:
    return r'''
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import traceback
from pathlib import Path


def _network_error(exc: BaseException) -> bool:
    try:
        import httpx
    except Exception:
        httpx = None
    if httpx is not None and isinstance(exc, httpx.HTTPError):
        return True
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


async def _main() -> None:
    package_root = Path(sys.argv[1])
    api_root = Path(sys.argv[2])
    manifest_path = Path(sys.argv[3])
    config_path = Path(sys.argv[4])
    sys.path.insert(0, str(package_root))
    sys.path.insert(0, str(api_root))

    from gremlinboard_api.schemas.contracts import WidgetManifest
    from gremlinboard_api.runtime.base import ServiceContext

    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = WidgetManifest.model_validate(manifest_payload)
    module = importlib.import_module(f"widgets.{manifest.id}.backend")
    service_class = getattr(module, manifest.service.class_name)
    service = service_class(
        instance_id="dry-run",
        manifest=manifest,
        config=config,
        service_context=ServiceContext(provider_registry=None),
    )
    try:
        await service.start()
        state = await service.get_state()
    except BaseException as exc:
        if _network_error(exc):
            print(json.dumps({"ok": True, "state": getattr(service, "state", {}), "degraded": True, "error": str(exc)}))
            return
        print(json.dumps({"ok": False, "error": "".join(traceback.format_exception_only(type(exc), exc)).strip()}))
        return
    print(json.dumps({"ok": True, "state": state}))


asyncio.run(_main())
'''.strip() + "\n"