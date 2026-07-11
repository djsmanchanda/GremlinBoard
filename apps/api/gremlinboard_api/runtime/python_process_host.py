"""Host generated Python widget services behind JSON-RPC stdio.

The parent launches Python with ``-I`` so user-site packages and Python environment
variables cannot affect the child. A small ``-c`` bootstrap inserts the absolute
``apps/api`` root before importing this module; this host then inserts the absolute
widgets parent supplied in argv. This avoids relying on ``PYTHONPATH``, which
isolated mode intentionally ignores.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from gremlinboard_api.runtime.base import BaseWidgetService, ServiceContext
from gremlinboard_api.schemas.contracts import WidgetManifest


def _respond(request_id: Any, *, result: Any = None, error: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        payload["result"] = result
    else:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _load_manifest(widgets_parent: Path, widget_id: str) -> WidgetManifest:
    manifest_path = widgets_parent / "widgets" / widget_id / "manifest.json"
    return WidgetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


async def _serve(widgets_parent: Path, widget_id: str, class_name: str) -> None:
    sys.path.insert(0, str(widgets_parent))
    manifest = _load_manifest(widgets_parent, widget_id)
    module_name = f"widgets.{widget_id}.backend"
    with redirect_stdout(sys.stderr):
        module = importlib.import_module(module_name)
        service_class = getattr(module, class_name)

    service: BaseWidgetService | None = None
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _respond(None, error={"code": -32700, "message": "parse error"})
            continue
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            request_id = request.get("id") if isinstance(request, dict) else None
            _respond(request_id, error={"code": -32600, "message": "invalid request"})
            continue

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            _respond(request_id, error={"code": -32602, "message": "invalid params"})
            continue
        if method not in {"start", "stop", "health", "get_state", "refresh", "set_config"}:
            _respond(request_id, error={"code": -32601, "message": "method not found"})
            continue

        try:
            with redirect_stdout(sys.stderr):
                if method == "start":
                    service = service_class(
                        instance_id=str(params.get("instance_id") or ""),
                        manifest=manifest,
                        config=dict(params.get("config") or {}),
                        service_context=ServiceContext(provider_registry=None),
                    )
                    if not isinstance(service, BaseWidgetService):
                        raise TypeError(f"widget service {widget_id} must inherit BaseWidgetService")
                    result = await service.start()
                elif service is None:
                    raise RuntimeError("service is not started")
                elif method == "stop":
                    result = await service.stop()
                elif method == "health":
                    result = await service.health()
                elif method == "get_state":
                    result = await service.get_state()
                elif method == "refresh":
                    result = await service.refresh(force=bool(params.get("force", False)))
                else:
                    result = await service.set_config(dict(params.get("config") or {}))
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            _respond(request_id, error={"code": -32000, "message": str(exc) or type(exc).__name__})
            continue

        _respond(request_id, result=result)
        if method == "stop":
            return


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: python_process_host <widgets_parent_dir> <widget_id> <class_name>", file=sys.stderr)
        return 2
    widgets_parent, widget_id, class_name = args
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(Path(widgets_parent).resolve(), widget_id, class_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
