#!/bin/sh
# Run with: sh launch_studio.sh [--check] [--no-install] [--port 8001]
set -eu
studio_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${ORNAMENT_PYTHON:-}" ]; then
  exec "$ORNAMENT_PYTHON" "$studio_root/setup/start_studio.py" "$@"
fi
for studio_python in python3.12 python3 python; do
  if command -v "$studio_python" >/dev/null 2>&1 && "$studio_python" -c 'import sys; raise SystemExit(sys.version_info < (3,11))' 2>/dev/null; then
    exec "$studio_python" "$studio_root/setup/start_studio.py" "$@"
  fi
done
echo 'Python 3.11+ was not found. Install Python 3.12 and its venv module, or set ORNAMENT_PYTHON.' >&2
exit 1
