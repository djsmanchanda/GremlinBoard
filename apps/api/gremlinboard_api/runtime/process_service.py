from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gremlinboard_api.runtime.base import BaseWidgetService, ServiceContext
from gremlinboard_api.schemas.contracts import ProcessServiceTarget, WidgetManifest

logger = logging.getLogger(__name__)


class ProcessServiceError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ProcessWidgetService(BaseWidgetService):
    def __init__(
        self,
        *,
        instance_id: str,
        manifest: WidgetManifest,
        config: dict[str, Any],
        widget_root: Path,
        service_context: ServiceContext | None = None,
        command: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        super().__init__(
            instance_id=instance_id,
            manifest=manifest,
            config=config,
            service_context=service_context,
        )
        if command is None and not isinstance(manifest.service, ProcessServiceTarget):
            raise TypeError("ProcessWidgetService requires a process service manifest")
        self.widget_root = widget_root
        # On Windows a child whose cwd is the widget package dir locks that dir
        # against uninstall/rollback deletion, so hosts that use absolute paths
        # can pass a neutral cwd instead.
        self._cwd = cwd if cwd is not None else widget_root
        self.process_service = manifest.service if isinstance(manifest.service, ProcessServiceTarget) else None
        self._command = list(command) if command is not None else None
        if self._command is not None and not self._command:
            raise ValueError("explicit process command must not be empty")
        self._env = dict(env) if env is not None else None
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._call_lock = asyncio.Lock()
        self._next_request_id = 1

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        command = self._resolve_command()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self._cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError as exc:
            raise ProcessServiceError(
                "spawn_failed",
                str(exc),
                {"error_type": type(exc).__name__, "command": command[0]},
            ) from exc
        self._stderr_task = asyncio.create_task(
            self._read_stderr(),
            name=f"widget-process-stderr-{self.instance_id}",
        )
        try:
            await self._call(
                "start",
                {"instance_id": self.instance_id, "config": self.config},
                timeout=self.manifest.runtime_policy.start_timeout_seconds,
            )
        except Exception:
            await self._terminate_process()
            raise

    async def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            with contextlib.suppress(ProcessServiceError):
                await self._call("stop", {}, timeout=self._stop_call_timeout_seconds())
        await self._terminate_process()

    async def health(self) -> dict[str, Any]:
        process = self._process
        if process is None:
            return self._unhealthy("process is not started", exit_code=None)
        if process.returncode is not None:
            return self._unhealthy("process exited", exit_code=process.returncode)
        try:
            result = await self._call("health", {}, timeout=self.manifest.runtime_policy.refresh_timeout_seconds)
        except ProcessServiceError as exc:
            if exc.code in {"eof", "process_not_running"}:
                exit_code = self._process.returncode if self._process is not None else None
                return self._unhealthy(exc.message, exit_code=exit_code)
            raise
        if not isinstance(result, dict):
            raise ProcessServiceError(
                "invalid_result",
                "health returned a non-object result",
                {"method": "health", "result_type": type(result).__name__},
            )
        return result

    async def get_state(self) -> dict[str, Any]:
        result = await self._call("get_state", {}, timeout=self.manifest.runtime_policy.refresh_timeout_seconds)
        if not isinstance(result, dict):
            raise ProcessServiceError(
                "invalid_result",
                "get_state returned a non-object result",
                {"method": "get_state", "result_type": type(result).__name__},
            )
        self.state = result
        return result

    async def refresh(self, *, force: bool = False) -> dict[str, Any]:
        self._force_refresh_requested = force
        try:
            result = await self._call(
                "refresh",
                {"force": force},
                timeout=self.manifest.runtime_policy.refresh_timeout_seconds,
            )
            if not isinstance(result, dict):
                raise ProcessServiceError(
                    "invalid_result",
                    "refresh returned a non-object result",
                    {"method": "refresh", "result_type": type(result).__name__},
                )
            self.state = result
            return result
        finally:
            self._force_refresh_requested = False

    async def set_config(self, config: dict[str, Any]) -> None:
        self.config = config
        await self._call(
            "set_config",
            {"config": config},
            timeout=self.manifest.runtime_policy.refresh_timeout_seconds,
        )

    async def _call(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        async with self._call_lock:
            process = self._require_running_process()
            if process.stdin is None or process.stdout is None:
                raise ProcessServiceError("stdio_unavailable", "process stdio pipes are not available")
            request_id = self._next_request_id
            self._next_request_id += 1
            request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            try:
                line = json.dumps(request, separators=(",", ":")) + "\n"
            except TypeError as exc:
                raise ProcessServiceError(
                    "invalid_params",
                    str(exc),
                    {"method": method, "error_type": type(exc).__name__},
                ) from exc
            try:
                process.stdin.write(line.encode("utf-8"))
                await asyncio.wait_for(process.stdin.drain(), timeout=timeout)
                response_line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
            except TimeoutError as exc:
                raise ProcessServiceError(
                    "timeout",
                    f"JSON-RPC method '{method}' timed out",
                    {"method": method, "timeout_seconds": timeout},
                ) from exc
            except (BrokenPipeError, ConnectionResetError) as exc:
                exit_code = await self._wait_for_process_returncode()
                raise ProcessServiceError(
                    "eof",
                    "process stdio closed before a response was received",
                    {"method": method, "exit_code": exit_code},
                ) from exc
            if response_line == b"":
                exit_code = await self._wait_for_process_returncode()
                raise ProcessServiceError(
                    "eof",
                    "process exited before a response was received",
                    {"method": method, "exit_code": exit_code},
                )
            try:
                response = json.loads(response_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProcessServiceError(
                    "malformed_json",
                    "process returned malformed JSON",
                    {"method": method, "line": response_line.decode("utf-8", errors="replace")},
                ) from exc
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
                raise ProcessServiceError(
                    "malformed_response",
                    "process returned an invalid JSON-RPC response",
                    {"method": method, "response": response},
                )
            if "error" in response:
                error = response.get("error")
                message = "process returned a JSON-RPC error"
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
                raise ProcessServiceError(
                    "jsonrpc_error",
                    message,
                    {"method": method, "error": error},
                )
            return response.get("result")

    def _require_running_process(self) -> asyncio.subprocess.Process:
        process = self._process
        if process is None:
            raise ProcessServiceError("process_not_running", "process is not started")
        if process.returncode is not None:
            raise ProcessServiceError(
                "process_not_running",
                "process has exited",
                {"exit_code": process.returncode},
            )
        return process

    async def _terminate_process(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            with contextlib.suppress(Exception):
                await process.stdin.wait_closed()
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await asyncio.wait_for(process.wait(), timeout=3.0)
        await self._finish_stderr_task()
        self._process = None

    async def _finish_stderr_task(self) -> None:
        task = self._stderr_task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            self._stderr_task = None

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if line == b"":
                return
            logger.warning(
                "widget process stderr widget_id=%s instance_id=%s: %s",
                self.manifest.id,
                self.instance_id,
                line.decode("utf-8", errors="replace").rstrip(),
            )

    async def _wait_for_process_returncode(self) -> int | None:
        process = self._process
        if process is None:
            return None
        if process.returncode is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=0.2)
        return process.returncode

    def _resolve_command(self) -> list[str]:
        if self._command is not None:
            return list(self._command)
        if self.process_service is None:  # pragma: no cover - guarded by __init__
            raise TypeError("process service target is unavailable")
        command = list(self.process_service.command)
        executable = command[0]
        if _is_path_like(executable):
            executable_path = Path(executable)
            if not executable_path.is_absolute():
                executable_path = self.widget_root / executable_path
            command[0] = str(executable_path.resolve(strict=False))
        return command

    def _stop_call_timeout_seconds(self) -> float:
        return float(min(max(self.manifest.runtime_policy.start_timeout_seconds, 1), 3))

    @staticmethod
    def _unhealthy(message: str, *, exit_code: int | None) -> dict[str, Any]:
        return {
            "status": "unhealthy",
            "healthy": False,
            "expired": False,
            "message": message,
            "exit_code": exit_code,
        }


def _is_path_like(value: str) -> bool:
    return "/" in value or "\\" in value or Path(value).is_absolute()