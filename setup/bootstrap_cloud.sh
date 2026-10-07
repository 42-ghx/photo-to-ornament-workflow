#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    echo "This installer requires Linux x86_64. Use the Windows setup on your PC." >&2
    exit 1
fi
if [[ -n "${PYTHON_BIN:-}" ]]; then
    task_python="$PYTHON_BIN"
elif command -v python3.12 >/dev/null; then
    task_python="$(command -v python3.12)"
else
    task_python="$(command -v python3)"
fi
"$task_python" -c 'import sys; assert sys.version_info[:2] == (3,12), "Provide Python 3.12 via PYTHON_BIN"'
if command -v apt-get >/dev/null; then
    task_sudo=()
    if [[ "$(id -u)" != 0 ]]; then task_sudo=(sudo -n); fi
    "${task_sudo[@]}" apt-get update
    "${task_sudo[@]}" apt-get install -y git-lfs curl xz-utils xvfb xauth libx11-6 libxxf86vm1 libxfixes3 libxi6 libxrender1 libxkbcommon0 libsm6 libice6 libgl1 libegl1 libgomp1 libdbus-1-3
fi
git lfs install --local
git lfs pull
"$task_python" -m venv .venv
.venv/bin/python -m pip install -r setup/requirements.txt
mkdir -p .tools
task_blender_version=5.2.2
task_archive="blender-${task_blender_version}-linux-x64.tar.xz"
task_download="https://download.blender.org/release/Blender5.2"
if [[ ! -x ".tools/blender-${task_blender_version}-linux-x64/blender" ]]; then
    curl --fail --location --retry 3 "$task_download/$task_archive" -o ".tools/$task_archive"
    curl --fail --location --retry 3 "$task_download/blender-${task_blender_version}.sha256" -o ".tools/blender-${task_blender_version}.sha256"
    (cd .tools && awk -v name="$task_archive" '$2 == name || $2 == "*"name {print}' "blender-${task_blender_version}.sha256" > selected.sha256 && test -s selected.sha256 && sha256sum -c selected.sha256)
    tar -xJf ".tools/$task_archive" -C .tools
fi
".tools/blender-${task_blender_version}-linux-x64/blender" --version
.venv/bin/python setup/verify_manifest.py
echo "Ready: .venv/bin/python run_case.py --blender .tools/blender-${task_blender_version}-linux-x64/blender"
