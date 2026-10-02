import os
import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; leaving it unchanged.")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(
        "EDGEGUARD_API_KEY="
        + secrets.token_urlsafe(32)
        + "\nEDGEGUARD_ENABLE_FAULTS=0\n"
    )
print("Created .env. Open it locally to copy your node access key. Do not commit it.")
