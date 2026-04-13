#!/usr/bin/env sh
set -eu

export PYTHONPATH="$PWD:$PWD/apps/api"
uvicorn --app-dir apps/api gremlinboard_api.main:app --reload --host 127.0.0.1 --port 8000
