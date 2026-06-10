from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PureWindowsPath
from typing import Any

import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gremlinboard_api import GREMLINBOARD_VERSION


DEFAULT_API_PORTS = {"stable": 2555, "dev": 2556}


class CliError(Exception):
    pass


def run(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    prog: str = "gremlinboard",
) -> int:
    parser = _build_parser(prog=prog)
    args = parser.parse_args(argv)

    try:
        if args.command == "start":
            return _start_launcher(args.mode)
        if args.command == "stop":
            return _stop_launcher()
        if args.command == "kill":
            return _stop_launcher(mode=None if args.all else args.mode)

        api_url = _api_url(args)
        with client_factory(base_url=api_url, timeout=10.0) as client:
            payload = _dispatch_http_command(args, client)
        _print_payload(args, payload)
        return 0
    except (CliError, httpx.HTTPError) as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run(argv, prog=_program_name()))


def _build_parser(*, prog: str = "gremlinboard") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="GremlinBoard local operator control plane.",
        epilog=(
            "Operator commands:\n"
            "  runtime      Inspect or change runtime power state\n"
            "  widgets      List and control board widgets\n"
            "  board        Inspect board snapshots\n"
            "  agents       Inspect local agent sessions and tasks\n"
            "  jobs         Inspect staged generation jobs\n"
            "  approvals    Review destructive action requests\n"
            "  devtools     Inspect runtime diagnostics\n"
            "  kill         Stop managed instances for this CLI mode\n\n"
            "Compatibility commands:\n"
            "  control      Legacy typed control namespace\n"
            "  status, registry, logs, start, stop\n\n"
            "Use '<command> --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=_version_text(prog))
    parser.add_argument(
        "--mode",
        choices=sorted(DEFAULT_API_PORTS),
        default=_default_mode(prog),
        help="Target stable or dev API.",
    )
    parser.add_argument("--api-url", default=os.environ.get("GREMLINBOARD_API_URL"), help="Override the local API URL.")
    parser.add_argument("--json", action="store_true", help="Print raw machine-readable JSON.")
    parser.set_defaults(program_name=prog)

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    subparsers.add_parser("status", help="Show legacy API health summary.")

    board = subparsers.add_parser("board", help="Inspect the board.")
    board.add_argument("board_action", nargs="?", choices=["snapshot"], help="Typed board operation.")

    subparsers.add_parser("registry", help="List registered widgets.")

    logs = subparsers.add_parser("logs", help="Show runtime logs.")
    logs.add_argument("--limit", type=int, default=50)

    _add_widgets_parser(subparsers.add_parser("widgets", help="Inspect and control widgets."))
    _add_runtime_parser(subparsers.add_parser("runtime", help="Inspect or change runtime power state."))
    _add_agents_parser(subparsers.add_parser("agents", help="Inspect local agent sessions and tasks."))
    _add_jobs_parser(subparsers.add_parser("jobs", help="Inspect staged generation jobs."))
    _add_approvals_parser(subparsers.add_parser("approvals", help="Review destructive action requests."))
    subparsers.add_parser("devtools", help="Inspect runtime diagnostics.")
    kill = subparsers.add_parser("kill", help="Stop tray-managed instances for this CLI mode.")
    kill.add_argument("--all", action="store_true", help="Stop stable and dev instances.")

    _add_control_parser(subparsers)

    start = subparsers.add_parser("start", help="Start the Windows tray launcher.")
    start.add_argument("--mode", choices=sorted(DEFAULT_API_PORTS), default="stable")
    subparsers.add_parser("stop", help="Stop tray-managed processes.")
    return parser


def _add_control_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    control = subparsers.add_parser("control", help="Compatibility alias for typed operator commands.")
    control_subparsers = control.add_subparsers(dest="control_area", metavar="COMMAND", required=True)
    _add_widgets_parser(control_subparsers.add_parser("widgets", help="Inspect and control widgets."))
    _add_runtime_parser(control_subparsers.add_parser("runtime", help="Inspect or change runtime power state."))

    board = control_subparsers.add_parser("board", help="Inspect the board.")
    board_subparsers = board.add_subparsers(dest="control_action", required=True)
    board_subparsers.add_parser("snapshot", help="Show the current board snapshot.")

    _add_jobs_parser(control_subparsers.add_parser("jobs", help="Inspect staged generation jobs."))
    _add_agents_parser(control_subparsers.add_parser("agents", help="Inspect local agent sessions and tasks."))
    _add_approvals_parser(control_subparsers.add_parser("approvals", help="Review destructive action requests."))


def _add_widgets_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="control_action", metavar="ACTION", required=True)
    subparsers.add_parser("list", help="List board widget instances.")
    add = subparsers.add_parser("add", help="Add a registered widget.")
    add.add_argument("widget_id")
    add.add_argument("--size", required=True)
    add.add_argument("--title")
    add.add_argument("--config-json", default="{}")
    for action in ("remove", "restart", "pause", "resume", "start", "stop", "refresh"):
        action_parser = subparsers.add_parser(action, help=f"{action.title()} a widget instance.")
        action_parser.add_argument("instance_id")
    resize = subparsers.add_parser("resize", help="Resize a widget instance.")
    resize.add_argument("instance_id")
    resize.add_argument("size")
    configure = subparsers.add_parser("configure", help="Update widget title or source settings.")
    configure.add_argument("instance_id")
    configure.add_argument("--title")
    configure.add_argument("--config-json")


def _add_runtime_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="control_action", metavar="ACTION", required=True)
    subparsers.add_parser("status", help="Show runtime status.")
    subparsers.add_parser("suspend", help="Suspend scheduled runtime work.")
    subparsers.add_parser("resume", help="Resume scheduled runtime work.")


def _add_agents_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="control_action", metavar="ACTION", required=True)
    list_parser = subparsers.add_parser("list", help="List agent sessions and tasks.")
    list_parser.add_argument("--status")
    list_parser.add_argument("--type")
    list_parser.add_argument("--source")


def _add_jobs_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="control_action", metavar="ACTION", required=True)
    list_parser = subparsers.add_parser("list", help="List staged generation jobs.")
    list_parser.add_argument("--widget-id")


def _add_approvals_parser(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="control_action", metavar="ACTION", required=True)
    subparsers.add_parser("list", help="List pending and resolved approvals.")
    for action in ("approve", "reject"):
        decision = subparsers.add_parser(action, help=f"{action.title()} a destructive action request.")
        decision.add_argument("approval_id")
        decision.add_argument("--note")


def _api_url(args: argparse.Namespace) -> str:
    if args.api_url:
        return args.api_url.rstrip("/")
    port = DEFAULT_API_PORTS[args.mode]
    return f"http://127.0.0.1:{port}/api"


def _dispatch_http_command(args: argparse.Namespace, client: httpx.Client) -> Any:
    if args.command == "status":
        return _request_json(client, "GET", "/health")
    if args.command == "board" and args.board_action is None:
        return _request_json(client, "GET", "/board")
    if args.command == "registry":
        return _request_json(client, "GET", "/registry/widgets")
    if args.command == "logs":
        return _request_json(client, "GET", "/runtime/logs", params={"limit": args.limit})
    if args.command == "devtools":
        return _request_json(client, "GET", "/devtools/snapshot")
    if args.command == "control":
        return _dispatch_control_command(args, client)
    if args.command == "runtime" and not _uses_short_operator_commands(args.program_name):
        return _dispatch_legacy_runtime_command(args, client)
    if args.command == "widgets" and args.control_action in {"start", "stop", "refresh"}:
        return _request_json(client, "POST", f"/board/widgets/{args.instance_id}/{args.control_action}")
    if args.command in {"runtime", "widgets", "agents", "jobs", "approvals"} or (
        args.command == "board" and args.board_action == "snapshot"
    ):
        return _dispatch_control_command(args, client)
    raise CliError(f"unsupported command '{args.command}'")


def _dispatch_legacy_runtime_command(args: argparse.Namespace, client: httpx.Client) -> Any:
    if args.control_action == "status":
        return _request_json(client, "GET", "/runtime/status")
    if args.control_action in {"suspend", "resume"}:
        return _request_json(client, "POST", f"/runtime/{args.control_action}")
    raise CliError("unsupported runtime command")


def _dispatch_control_command(args: argparse.Namespace, client: httpx.Client) -> Any:
    area = _control_area(args)
    if area == "approvals":
        if args.control_action == "list":
            return _request_json(client, "GET", "/control/approvals")
        body = {"source": "cli", "note": args.note}
        return _request_json(client, "POST", f"/control/approvals/{args.approval_id}/{args.control_action}", json=body)

    action_id, params = _control_action(args, area=area)
    return _request_json(
        client,
        "POST",
        f"/control/actions/{action_id}",
        json={"source": "cli", "params": params},
    )


def _control_action(args: argparse.Namespace, *, area: str) -> tuple[str, dict[str, Any]]:
    if area == "widgets":
        if args.control_action == "list":
            return "widgets.list", {}
        if args.control_action == "add":
            return (
                "widgets.add",
                {
                    "widget_id": args.widget_id,
                    "title": args.title,
                    "size": args.size,
                    "config": _parse_json_arg(args.config_json, "--config-json"),
                },
            )
        if args.control_action in {"remove", "restart", "pause", "resume"}:
            return f"widgets.{args.control_action}", {"widget_instance_id": args.instance_id}
        if args.control_action == "resize":
            return "widgets.resize", {"widget_instance_id": args.instance_id, "size": args.size}
        if args.control_action == "configure":
            params: dict[str, Any] = {"widget_instance_id": args.instance_id}
            if args.title is not None:
                params["title"] = args.title
            if args.config_json is not None:
                params["config"] = _parse_json_arg(args.config_json, "--config-json")
            return "widgets.configure", params
    if area == "runtime":
        return f"runtime.{args.control_action}", {}
    if area == "board":
        return "board.snapshot", {}
    if area == "jobs" and args.control_action == "list":
        return "jobs.list", {"widget_id": args.widget_id} if args.widget_id else {}
    if area == "agents" and args.control_action == "list":
        return (
            "agents.list",
            {
                key: value
                for key, value in {"status": args.status, "type": args.type, "source": args.source}.items()
                if value is not None
            },
        )
    raise CliError("unsupported control command")


def _parse_json_arg(value: str, flag_name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise CliError(f"{flag_name} must be valid JSON: {exc.msg}") from exc


def _request_json(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("x-gremlin-presence-source", "cli")
    response = client.request(method, path, headers=headers, **kwargs)
    if response.status_code >= 400:
        raise CliError(f"{method} {path} failed with HTTP {response.status_code}: {response.text}")
    return response.json()


def _print_payload(args: argparse.Namespace, payload: Any) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    if args.command == "status":
        print("GremlinBoard API {status}: registry={registry_size} active_runners={active_runners}".format(**payload))
        return
    if args.command == "runtime":
        if _uses_short_operator_commands(args.program_name):
            _print_control_payload(args, payload)
            return
        if args.control_action in {"suspend", "resume"}:
            print("Runtime {state}: reason={reason}".format(**payload))
            return
        _print_runtime_status(payload)
        return
    if args.command == "board" and args.board_action is None:
        _print_board(payload)
        return
    if args.command == "registry":
        _print_registry(payload)
        return
    if args.command == "logs":
        _print_logs(payload)
        return
    if args.command == "devtools":
        _print_devtools(payload)
        return
    if args.command == "widgets" and args.control_action in {"start", "stop", "refresh"}:
        print(f"Widget {args.control_action} accepted. Board now has {len(payload.get('widgets', []))} widget(s).")
        return
    _print_control_payload(args, payload)


def _print_control_payload(args: argparse.Namespace, response: dict[str, Any]) -> None:
    area = _control_area(args)
    if area == "approvals" and args.control_action == "list":
        _print_approvals(response.get("approvals", []))
        return

    action_id = response["action_id"]
    payload = response.get("payload")
    if response["status"] == "completed":
        if action_id == "widgets.list":
            _print_widgets(payload or [])
            return
        if action_id == "agents.list":
            _print_agents(payload or [])
            return
        if action_id == "jobs.list":
            _print_jobs(payload or [])
            return
        if action_id == "board.snapshot":
            _print_board(payload or {})
            return
        if action_id == "runtime.status":
            _print_runtime_status(payload or {})
            return

    console = _console()
    console.print(
        Panel.fit(
            f"[bold]{action_id}[/bold]\n"
            f"Status: {_status_markup(response['status'])}\n"
            f"{action_id}: {response['status']} ({response['correlation_id']})",
            title="GremlinControl",
        )
    )
    approval = response.get("approval")
    if approval:
        table = _table("Approval Required", "Field", "Value")
        table.add_row("ID", str(approval["id"]))
        table.add_row("Action", str(approval["action_id"]))
        table.add_row("Status", str(approval["status"]))
        table.add_row("Reason", str(approval["reason"]))
        console.print(table)
        console.print(f"Approval {approval['id']}: {approval['status']} - {approval['reason']}")
    console.print(f"[dim]Correlation:[/dim] {response['correlation_id']}")


def _print_runtime_status(payload: dict[str, Any]) -> None:
    console = _console()
    state = str(payload.get("state", "unknown"))
    console.print(Panel.fit(f"State: {_status_markup(state)}", title="Runtime"))
    table = _table("Runtime Summary", "Metric", "Value")
    rows = [
        ("Active runners", payload.get("active_runners", 0)),
        ("Websocket subscribers", payload.get("websocket_subscribers", 0)),
        ("Monitor cadence", f"{payload.get('monitor_cadence_seconds', 0)}s"),
        ("Event queue depth", payload.get("queue_depth", 0)),
        ("Dropped events", payload.get("dropped_event_count", 0)),
        ("Registry size", payload.get("registry_size", 0)),
        ("Active agents", payload.get("active_agents", payload.get("agents", {}).get("active_agents", 0))),
    ]
    if "widgets_total" in payload:
        rows.insert(6, ("Widgets total", payload["widgets_total"]))
    for label, value in rows:
        table.add_row(label, str(value))
    console.print(table)
    runners = payload.get("runners", [])
    if runners:
        runner_table = _table("Widget Runners", "Instance", "Widget", "Mode", "State", "Restarts")
        for runner in runners:
            runner_table.add_row(
                str(runner.get("instance_id", "-")),
                str(runner.get("widget_id", "-")),
                str(runner.get("refresh_mode", "-")),
                str(runner.get("lifecycle_state", runner.get("state", "running"))),
                str(runner.get("restart_count", 0)),
            )
        console.print(runner_table)


def _print_widgets(widgets: list[dict[str, Any]]) -> None:
    console = _console()
    table = _table(f"Widgets ({len(widgets)})", "Instance", "Widget", "Title", "Size", "State", "Restarts")
    for widget in widgets:
        table.add_row(
            str(widget.get("id", "-")),
            str(widget.get("widget_id", "-")),
            str(widget.get("title", "-")),
            str(widget.get("size", "-")),
            str(widget.get("lifecycle_state", "-")),
            str(widget.get("restart_count", 0)),
        )
    console.print(table)


def _print_agents(agents: list[dict[str, Any]]) -> None:
    console = _console()
    table = _table(f"Agents ({len(agents)})", "ID", "Type", "Name", "Source", "Status", "Progress")
    for agent in agents:
        table.add_row(
            str(agent.get("id", "-")),
            str(agent.get("type", "-")),
            str(agent.get("name", "-")),
            str(agent.get("source", "-")),
            str(agent.get("status", "-")),
            f"{agent.get('progress', 0)}%",
        )
    console.print(table)


def _print_jobs(jobs: list[dict[str, Any]]) -> None:
    console = _console()
    table = _table(f"Generation Jobs ({len(jobs)})", "ID", "Widget", "Provider", "Status", "Progress", "Install")
    for job in jobs:
        table.add_row(
            str(job.get("id", "-")),
            str(job.get("widget_id", "-")),
            str(job.get("provider_id", "-")),
            str(job.get("status", "-")),
            f"{job.get('progress', 0)}%",
            "blocked" if job.get("install_blocked") else "ready",
        )
    console.print(table)


def _print_board(board: dict[str, Any]) -> None:
    console = _console()
    widgets = board.get("widgets", [])
    console.print(Panel.fit(f"[bold]{board.get('name', board.get('id', 'Board'))}[/bold]\nWidgets: {len(widgets)}", title="Board"))
    if widgets:
        _print_widgets(widgets)


def _print_approvals(approvals: list[dict[str, Any]]) -> None:
    console = _console()
    table = _table(f"Approvals ({len(approvals)})", "ID", "Action", "Status", "Source", "Requested")
    for approval in approvals:
        table.add_row(
            str(approval.get("id", "-")),
            str(approval.get("action_id", "-")),
            str(approval.get("status", "-")),
            str(approval.get("source", "-")),
            str(approval.get("requested_at", "-")),
        )
    console.print(table)


def _print_registry(payload: dict[str, Any]) -> None:
    console = _console()
    table = _table(f"Registry ({len(payload)})", "Widget", "Version", "Name")
    for widget_id in sorted(payload):
        manifest = payload[widget_id]["manifest"]
        table.add_row(widget_id, str(manifest["version"]), str(manifest["name"]))
    console.print(table)


def _print_logs(records: list[dict[str, Any]]) -> None:
    console = _console()
    table = _table(f"Runtime Logs ({len(records)})", "Created", "Level", "Event", "Message")
    for record in records:
        table.add_row(
            str(record.get("created_at", "-")),
            str(record.get("level", "-")),
            str(record.get("event", "-")),
            str(record.get("message", "-")),
        )
    console.print(table)


def _print_devtools(payload: dict[str, Any]) -> None:
    console = _console()
    runtime = payload.get("runtime", {})
    queues = payload.get("queues", {})
    replay = payload.get("replay", {})
    pressure = payload.get("pressure", {})
    console.print(Panel.fit(f"Runtime: {_status_markup(str(runtime.get('state', 'unknown')))}", title="Devtools"))
    table = _table("Diagnostics", "Area", "Status", "Detail")
    table.add_row("Queues", str(queues.get("health", "-")), f"event={queues.get('event_bus_queue_depth', 0)}")
    table.add_row("Replay", str(pressure.get("replay_pressure", "-")), f"history={replay.get('history_size', 0)}")
    table.add_row("Subscribers", str(pressure.get("subscriber_pressure", "-")), f"websocket={payload.get('websocket', {}).get('subscriber_count', 0)}")
    table.add_row("Providers", str(pressure.get("provider_pressure", "-")), f"degraded={len(payload.get('providers', {}).get('degradation', []))}")
    console.print(table)


def _table(title: str, *columns: str) -> Table:
    table = Table(title=title, box=box.SIMPLE_HEAD, header_style="bold cyan")
    for column in columns:
        table.add_column(column)
    return table


def _status_markup(status: str) -> str:
    style = {
        "active": "green",
        "completed": "green",
        "ok": "green",
        "running": "green",
        "idle": "yellow",
        "approval_required": "yellow",
        "pending": "yellow",
        "suspended": "yellow",
        "degraded": "red",
        "error": "red",
        "failed": "red",
        "rejected": "red",
    }.get(status, "white")
    return f"[{style}]{status}[/{style}]"


def _console() -> Console:
    return Console(highlight=False)


def _control_area(args: argparse.Namespace) -> str:
    return args.control_area if args.command == "control" else args.command


def _cli_version() -> str:
    try:
        return version("gremlinboard-api")
    except PackageNotFoundError:
        return "0.1.0"


def _version_text(prog: str) -> str:
    return f"GremlinBoard version: {GREMLINBOARD_VERSION}\n{prog} CLI version: {_cli_version()}"


def _program_name() -> str:
    name = Path(sys.argv[0]).stem.lower()
    return name if name in {"gb", "gb_dev"} else "gremlinboard"


def _default_mode(prog: str) -> str:
    return "dev" if prog == "gb_dev" else "stable"


def _uses_short_operator_commands(prog: str) -> bool:
    return prog in {"gb", "gb_dev"}


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
            _windows_launcher_arg(launcher),
            "-Mode",
            mode,
        ],
        cwd=str(_repo_root()),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"Started GremlinBoard {mode} launcher.")
    return 0


def _stop_launcher(*, mode: str | None = None) -> int:
    launcher = _launcher_path()
    if platform.system().lower() != "windows":
        raise CliError("stop is currently backed by the Windows tray launcher")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        _windows_launcher_arg(launcher),
    ]
    command.extend(["-StopMode", mode] if mode is not None else ["-StopAll"])
    completed = subprocess.run(
        command,
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


def _windows_launcher_arg(path: Path) -> str:
    return str(PureWindowsPath(path))


if __name__ == "__main__":
    main()
