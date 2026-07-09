# GremlinBoard Rust Widget Kit

This kit is the source-only starting point for out-of-process Rust widgets.
It implements the GremlinBoard process service protocol: newline-delimited JSON-RPC 2.0 over stdio.

No Rust toolchain is required to read or install this source. Building a widget requires rustup and cargo on the developer machine.

## Layout

- `src/protocol.rs` is reusable JSON-RPC glue exposed as the `gremlinboard_widget_kit` library.
- `src/main.rs` is a runnable template service.
- `Cargo.toml` depends only on `serde`, `serde_json`, and `std`.

## Service Trait

Implement `WidgetService`:

| Method | Params | Result |
| --- | --- | --- |
| `start` | `{ "instance_id": "...", "config": {...} }` | Any JSON object |
| `stop` | `{}` | Any JSON value, then the process exits |
| `health` | `{}` | Health JSON object |
| `get_state` | `{}` | Widget state JSON object |
| `refresh` | `{ "force": true }` | Widget state JSON object |
| `set_config` | `{ "config": {...} }` | Any JSON value |

Unknown methods return JSON-RPC error code `-32601`.

## Protocol Examples

Start request:

```json
{"jsonrpc":"2.0","id":1,"method":"start","params":{"instance_id":"example-1","config":{"label":"Rust"}}}
```

Start response:

```json
{"jsonrpc":"2.0","id":1,"result":{"status":"running","started":true,"uptime_seconds":0,"refresh_count":0,"config":{"label":"Rust"}}}
```

Refresh request:

```json
{"jsonrpc":"2.0","id":2,"method":"refresh","params":{"force":true}}
```

Stop request:

```json
{"jsonrpc":"2.0","id":3,"method":"stop","params":{}}
```

## Rules

- Write exactly one JSON-RPC response line to stdout for every request.
- Flush stdout after every response.
- Write human diagnostics to stderr only.
- Exit gracefully after sending the `stop` response.
- Keep binaries and commands inside the widget package directory. The registry rejects process commands that escape the package.

## Build The Template

From this directory, on a machine with rustup:

```powershell
cargo build --release
```

Use `widgets_examples/sysstats_rust` for a complete widget package example.