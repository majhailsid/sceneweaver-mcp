#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
if [ -f sceneweaver_mcp-0.1.0-py3-none-any.whl ]; then
  .venv/bin/python -m pip install './sceneweaver_mcp-0.1.0-py3-none-any.whl[voice]'
else
  .venv/bin/python -m pip install '.[voice]'
fi
.venv/bin/sceneweaver-mcp doctor
printf '%s\n' 'Installed. To download local voice models, run:' '.venv/bin/sceneweaver-mcp setup-voice' "MCP launcher: $PWD/examples/run-posix.sh"
