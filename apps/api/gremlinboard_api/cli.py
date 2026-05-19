from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx


DEFAULT_API_PORTS = {"stable": 2555, "dev": 2556}


class CliError(Exception):
    pass


def run(argv: list[str] | None = None, *, client_factory: Callable[..., httpx.Client] = httpx.Client) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "start":
            return _start_launcher(args.mode)
        if args.command == "stop":
            return _stop_launcher()

        api_url = _api_url(args)
        with client_factory(base_url=api_url, timeout=10.0) as client:
            payload = _dispatch_http_command(args, client)
        _print_payload(args, payload)
        return 0
    except (CliError, httpx.HTTPError) as exc:
        print(f"gremlinboard: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gremlinboard")
    parser.add_argument("--mode", choices=sorted(DEFAULT_API_PORTS), default="stable")
    parser.add_argument("--api-url", default=os.environ.get("GREMLINBOARD_API_URL"))
    parser.add_argument("--json", action="store_true", help="Print raw JSON responses.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("board")
    subparsers.add_parser("registry")

    logs = subparsers.add_parser("logs")
    logs.add_argument("--limit", type=int, default=50)

    widgets = subparsers.add_parser("widgets")
    widgets.add_argument("action", choices=["start", "stop", "refresh"])
    widgets.add_argument("instance_id")

    runtime = subparsers.add_parser("runtime")
    runtime_subparsers = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_subparsers.add_parser("status")

    start = subparsers.add_parser("start")
    start.add_argument("--mode", choices=sorted(DEFAULT_API_PORTS), default="stable")

    subparsers.add_parser("stop")
    return parser


def _api_url(args: argparse.Namespace) -> str:
    if args.api_url:
        return args.api_url.rstrip("/")
    port = DEFAULT_API_PORTS[args.mode]
    return f"http://127.0.0.1:{port}/api"


def _dispatch_http_command(args: argparse.Namespace, client: httpx.Client) -> Any:
    if args.command == "status":
        return _request_json(client, "GET", "/health")
    if args.command == "board":
        return _request_json(client, "GET", "/board")
    if args.command == "registry":
        return _request_json(client, "GET", "/registry/widgets")
    if args.command == "logs":
        return _request_json(client, "GET", "/runtime/logs", params={"limit": args.limit})
    if args.command == "widgets":
        return _request_json(client, "POST", f"/board/widgets/{args.instance_id}/{args.action}")
    if args.command == "runtime" and args.runtime_command == "status":
        return _request_json(client, "GET", "/runtime/status")
    raise CliError(f"unsupported command '{args.command}'")


def _request_json(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise CliError(f"{method} {path} failed with HTTP {response.status_code}: {response.text}")
    return response.json()


def _print_payload(args: argparse.Namespace, payload: Any) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    if args.command == "status":
        print(
            "GremlinBoard API {status}: registry={registry_size} active_runners={active_runners}".format(
                **payload
            )
        )
        return
    if args.command == "runtime":
        print(
            "Runtime {state}: active_runners={active_runners} subscribers={websocket_subscribers} "
            "monitor={monitor_cadence_seconds}s queue_depth={queue_depth}".format(**payload)
        )
        if payload.get("provider_degradation"):
            print(f"Provider degradations: {len(payload['provider_degradation'])}")
        return
    if args.command == "board":
        widgets = payload.get("widgets", [])
        print(f"Board {payload.get('name', payload.get('id'))}: {len(widgets)} widget(s)")
        for widget in widgets:
            print(f"- {widget['id']} {widget['widget_id']} {widget['lifecycle_state']} {widget['title']}")
        return
    if args.command == "registry":
        print(f"Registry: {len(payload)} widget(s)")
        for widget_id in sorted(payload):
            manifest = payload[widget_id]["manifest"]
            print(f"- {widget_id} {manifest['version']} {manifest['name']}")
        return
    if args.command == "logs":
        for record in payload:
            print(f"{record['created_at']} {record['level']} {record['event']} {record['message']}")
        return
    if args.command == "widgets":
        print(f"Widget {args.action} accepted. Board now has {len(payload.get('widgets', []))} widget(s).")


def _start_launcher(mode: str) -> int:
    launcher = _launcher_path()
    if platform.system().lower() != "windows":
        raise CliError("start is currently backed by the Windows tray launcher")
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-Mode",
            mode,
        ],
        cwd=str(_repo_root()),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"Started GremlinBoard {mode} launcher.")
    return 0


def _stop_launcher() -> int:
    launcher = _launcher_path()
    if platform.system().lower() != "windows":
        raise CliError("stop is currently backed by the Windows tray launcher")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
            "-StopAll",
        ],
        cwd=str(_repo_root()),
        check=False,
    )
    return completed.returncode


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _launcher_path() -> Path:
    launcher = _repo_root() / "scripts" / "gremlinboard-tray.ps1"
    if not launcher.exists():
        raise CliError(f"launcher script was not found at {launcher}")
    return launcher


if __name__ == "__main__":
    main()
