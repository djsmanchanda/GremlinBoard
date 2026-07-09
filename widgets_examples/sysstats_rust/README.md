# Rust Process Stats Example

This is a complete source-only GremlinBoard widget package for a Rust process service.
It is kept under `widgets_examples/` so the registry does not try to load an unbuilt binary from `widgets/`.

The widget reports process-visible std-only telemetry:

- service uptime in seconds
- refresh tick count
- current and last-refresh Unix timestamps
- config-driven label and note

It does not report CPU or memory because this example intentionally avoids extra crates such as `sysinfo`.

## Build

Install rustup, then run:

```powershell
.\build.ps1
```

The script runs `cargo build --release` and copies:

```text
target\release\sysstats_rust.exe -> bin\sysstats_rust.exe
```

## Install Locally

After building, copy the whole package directory into `widgets/`:

```powershell
Copy-Item -Recurse -Force widgets_examples\sysstats_rust widgets\sysstats_rust
```

The process command in `manifest.json` is:

```json
["bin/sysstats_rust.exe"]
```

Process commands must live inside the widget package directory. Do not point a process widget at arbitrary host paths.

## Protocol

The runtime starts the executable with the widget package as the working directory and speaks JSON-RPC 2.0 over newline-delimited stdin/stdout.

Example request:

```json
{"jsonrpc":"2.0","id":1,"method":"health","params":{}}
```

Example response:

```json
{"jsonrpc":"2.0","id":1,"result":{"status":"running","healthy":true,"expired":false,"message":"process telemetry active"}}
```

Human diagnostics must go to stderr. Stdout is reserved for JSON-RPC response lines only.