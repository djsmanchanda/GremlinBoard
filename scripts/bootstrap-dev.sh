#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_NAME="${GREMLINBOARD_ENV_NAME:-gremlinboard}"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"

if command -v micromamba >/dev/null 2>&1; then
  MICROMAMBA_EXE="$(command -v micromamba)"
elif [[ -n "${LOCALAPPDATA:-}" && -x "$LOCALAPPDATA/micromamba/micromamba.exe" ]]; then
  MICROMAMBA_EXE="$LOCALAPPDATA/micromamba/micromamba.exe"
elif [[ -x "$HOME/AppData/Local/micromamba/micromamba.exe" ]]; then
  MICROMAMBA_EXE="$HOME/AppData/Local/micromamba/micromamba.exe"
else
  echo "micromamba was not found. Install micromamba or add it to PATH." >&2
  exit 1
fi

cd "$REPO_ROOT"
echo "micromamba: $MICROMAMBA_EXE"
echo "MAMBA_ROOT_PREFIX: $MAMBA_ROOT_PREFIX"

if "$MICROMAMBA_EXE" env list | grep -Eq "[/\\\\]envs[/\\\\]${ENV_NAME}([[:space:]]|$)"; then
  "$MICROMAMBA_EXE" install -n "$ENV_NAME" --override-channels -c conda-forge -f environment.yml -y
else
  "$MICROMAMBA_EXE" create -n "$ENV_NAME" --override-channels -c conda-forge -f environment.yml -y
fi

"$MICROMAMBA_EXE" run -n "$ENV_NAME" python -m pip install -e "apps/api[dev]"
"$MICROMAMBA_EXE" run -n "$ENV_NAME" python -c "import sys, fastapi, pydantic, sqlalchemy, gremlinboard_api; print(sys.executable); print(sys.version); print('backend-imports-ok')"

if [[ "${GREMLINBOARD_SKIP_FRONTEND:-0}" != "1" ]]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js was not found on PATH. Install Node outside micromamba." >&2
    exit 1
  fi

  NPM_CLI="/c/Program Files/nodejs/node_modules/npm/bin/npm-cli.js"
  if [[ -f "$NPM_CLI" ]]; then
    export NPM_CONFIG_PREFIX="C:\\Program Files\\nodejs"
  fi

  if [[ "${GREMLINBOARD_SKIP_NPM_CI:-0}" != "1" && ! -x "node_modules/.bin/tsc" && ! -f "node_modules/.bin/tsc.cmd" ]]; then
    if [[ -f "$NPM_CLI" ]]; then
      node "$NPM_CLI" ci
    else
      npm ci
    fi
  fi

  if [[ -f "node_modules/.bin/tsc.cmd" ]]; then
    "node_modules/.bin/tsc.cmd" -p apps/web/tsconfig.json --noEmit
  else
    "node_modules/.bin/tsc" -p apps/web/tsconfig.json --noEmit
  fi
fi

echo "GremlinBoard development environment is ready."
echo "Activate with: micromamba activate $ENV_NAME"
echo "Or run commands with: micromamba run -n $ENV_NAME <command>"
