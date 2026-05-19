#!/usr/bin/env sh
set -eu

NEXT_PUBLIC_GREMLINBOARD_API_URL="${NEXT_PUBLIC_GREMLINBOARD_API_URL:-http://127.0.0.1:2556/api}" npm --workspace apps/web run dev
