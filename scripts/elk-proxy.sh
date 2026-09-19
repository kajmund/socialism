#!/usr/bin/env bash

set -eu

flyctl_bin="${FLYCTL:-flyctl}"
fly_app="${ELASTICSEARCH_FLY_APP:-socialism-elasticsearch}"
local_port="${ELASTICSEARCH_PROXY_PORT:-19200}"
remote_port="${ELASTICSEARCH_REMOTE_PORT:-9200}"

if ! command -v "$flyctl_bin" >/dev/null 2>&1; then
  echo "ELK proxy: '$flyctl_bin' was not found. Install flyctl or set FLYCTL to its path." >&2
  exit 1
fi

if ! command -v lsof >/dev/null 2>&1; then
  echo "ELK proxy: lsof is required to verify the local port." >&2
  exit 1
fi

if ! "$flyctl_bin" auth whoami >/dev/null 2>&1; then
  echo "ELK proxy: Fly authentication is missing or expired. Run '$flyctl_bin auth login'." >&2
  exit 1
fi

if lsof -nP -iTCP:"$local_port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ELK proxy: local port $local_port is already in use." >&2
  exit 1
fi

echo "ELK proxy: http://127.0.0.1:$local_port -> $fly_app.internal:$remote_port"
exec "$flyctl_bin" proxy "$local_port:$remote_port" \
  --app "$fly_app" \
  --bind-addr 127.0.0.1
