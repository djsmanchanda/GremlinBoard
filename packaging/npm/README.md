# gremlinboard

Run the full GremlinBoard stack — API + web board — on your own machine with a
single command. No cloud account, no Docker, no manual setup: this package
downloads nothing but a couple of Python wheels' worth of dependencies on
first run, then everything runs locally.

## Requirements

- Node.js >= 18
- Python >= 3.12 available on `PATH` (as `py -3.12`, `python3.12`, `python3`,
  or `python`, depending on your platform)
- Network access on the *first* run only, so `pip` can install the API's
  dependencies into a private virtual environment

## Run it

```sh
npx gremlinboard
```

or install it globally:

```sh
npm install -g gremlinboard
gremlinboard
```

or with Bun:

```sh
bunx gremlinboard
```

The first run creates a Python virtual environment and installs the bundled
`gremlinboard-api` wheel into it — this needs network access and can take a
minute. Subsequent runs reuse the same environment and start in seconds.

Once running, GremlinBoard prints:

- Board:  http://127.0.0.1:7555
- System: http://127.0.0.1:7555/system
- Studio: http://127.0.0.1:7555/studio
- API:    http://127.0.0.1:2555/api

## Commands

| Command                | Description                                            |
| ----------------------- | ------------------------------------------------------- |
| `gremlinboard` / `gremlinboard start` | Start the API and web servers (default command) |
| `gremlinboard stop`     | Stop a running instance started by this CLI              |
| `gremlinboard status`   | Show whether GremlinBoard is running                     |
| `gremlinboard --help`   | Show usage                                                |

`start` refuses to run if ports 2555 or 7555 are already in use — it never
touches a process it didn't start.

## Where your data lives

This npm package is immutable and never writes inside itself. All state —
the SQLite database, session/auth data, custom widgets, provider API keys,
the Python virtual environment, and log files — lives in a platform-specific
data directory:

| Platform | Location                                              |
| -------- | ------------------------------------------------------ |
| Windows  | `%LOCALAPPDATA%\GremlinBoard`                           |
| macOS    | `~/Library/Application Support/GremlinBoard`            |
| Linux    | `$XDG_DATA_HOME/gremlinboard` or `~/.local/share/gremlinboard` |

Override the location with the `GREMLINBOARD_DATA_DIR` environment variable
(useful for running multiple isolated instances or for testing).

Any API keys or provider credentials you configure through the System panel
are stored in that data directory's SQLite database — never in this package,
never in source control.

## Logs

- `<data dir>/launcher/npm-api.log`
- `<data dir>/launcher/npm-web.log`

## Uninstalling

`npm uninstall -g gremlinboard` (or just stop using `npx`) removes the code.
Your data directory is left untouched; delete it manually if you want a full
clean slate.
