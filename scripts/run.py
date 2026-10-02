"""Cross-platform launcher. Run from repository root: python -m scripts.run"""

import os
import subprocess
import sys
import time
from pathlib import Path
from edgeguard.config import load_env

load_env()
if len(os.getenv("EDGEGUARD_API_KEY", "")) < 24:
    raise SystemExit("Run python scripts/configure.py first.")
if not Path("frontend/dist/index.html").exists():
    raise SystemExit("Build frontend first: cd frontend; npm ci; npm run build")
children = []
try:
    for role, port in [("cloud", 8001), ("edge", 8000)]:
        env = dict(
            os.environ,
            EDGEGUARD_ROLE=role,
            EDGEGUARD_DB=f"data/{role}.db",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
        )
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "edgeguard.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workers",
                    "1",
                ],
                env=env,
            )
        )
    print("Local: http://127.0.0.1:8000 | Cloud: http://127.0.0.1:8001", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for p in children:
        if p.poll() is None:
            p.terminate()
    for p in children:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
