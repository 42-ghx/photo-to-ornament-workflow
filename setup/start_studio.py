"""Launch the portable, loopback-only ornament studio using installed Python.

Python 3.11+ and the packages in requirements-studio.txt are required. This
launcher never installs software or accesses a package registry. It prefers a
project-local .venv-studio or .venv, then the interpreter running the launcher.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def runtime_status(python):
    probe = (
        "import json,sys,numpy,PIL; from importlib.metadata import version; "
        "assert sys.version_info >= (3,11); "
        "print(json.dumps({'python': sys.version.split()[0], 'packages': "
        "{k: version(k) for k in ('numpy','Pillow')}}))"
    )
    try:
        result = subprocess.run([str(python), "-c", probe], capture_output=True,
                                text=True, timeout=20)
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def prepare():
    candidates = []
    if os.environ.get("ORNAMENT_PYTHON"):
        candidates.append(Path(os.environ["ORNAMENT_PYTHON"]))
    for env in (".venv-studio", ".venv"):
        candidates.append(ROOT / env / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    candidates.append(Path(sys.executable))
    for python in dict.fromkeys(candidates):
        if python.is_file():
            status = runtime_status(python)
            if status:
                return python, status
    raise RuntimeError("Python 3.11+ with NumPy and Pillow is required. Run your chosen Python with "
                       "'-m pip install -r setup/requirements-studio.txt', or set ORNAMENT_PYTHON "
                       "to an existing environment that has them.")


def open_when_ready(url, process):
    local_http = build_opener(ProxyHandler({}))
    for _ in range(80):
        if process.poll() is not None:
            return
        try:
            with local_http.open(url + "api/capabilities", timeout=.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            time.sleep(.15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--check", action="store_true", help="Check dependencies and exit")
    parser.add_argument("--no-install", action="store_true", help="Compatibility flag; this launcher never installs")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        python, status = prepare()
        print("Studio runtime ready: " + json.dumps(status), flush=True)
        if args.check:
            return 0
        with socket.socket() as check_socket:
            try:
                check_socket.bind(("127.0.0.1", args.port))
            except OSError:
                raise RuntimeError(f"Port {args.port} is already in use. Choose another --port.") from None
        url = f"http://127.0.0.1:{args.port}/"
        print("Studio: " + url + " (local computer only). Ctrl+C stops the studio.", flush=True)
        process = subprocess.Popen([str(python), str(ROOT / "canvas/server.py"),
                                    "--host", "127.0.0.1", "--port", str(args.port)],
                                   cwd=str(ROOT), env={**os.environ, "PYTHONUTF8": "1"})
        if not args.no_browser:
            threading.Thread(target=open_when_ready, args=(url, process), daemon=True).start()
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Studio startup failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
