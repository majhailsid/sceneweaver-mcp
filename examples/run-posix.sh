#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$root/.venv/bin/sceneweaver-mcp" ]; then
  printf '%s\n' 'Run install-posix.sh first.' >&2
  exit 1
fi
exec "$root/.venv/bin/sceneweaver-mcp" serve
