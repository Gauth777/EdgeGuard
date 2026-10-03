"""Explicit opt-in for the synthetic evaluation model; preserves other .env settings."""

import argparse
from pathlib import Path
from scripts.evaluate_ml import build_and_evaluate


def configure(path, model, machine):
    path = Path(path)
    if not path.exists():
        raise ValueError("Run python scripts/configure.py first")
    original = path.read_text()
    changes = {"EDGEGUARD_MODEL": model, "EDGEGUARD_MODEL_MACHINE": machine}
    lines = original.splitlines()
    result = []
    for line in lines:
        name = line.split("=", 1)[0].strip()
        if name not in changes:
            result.append(line)
    result.extend(f"{name}={value}" for name, value in changes.items())
    # Write beside original first so a failed write does not truncate the original .env.
    temporary = path.with_name(path.name + ".ml-tmp")
    try:
        temporary.write_text("\n".join(result) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser(
        description="Train, evaluate and opt in to a SYNTHETIC model. Not industrial calibration."
    )
    p.add_argument("--machine", default="ML-01")
    args = p.parse_args()
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.machine):
        raise ValueError("Invalid machine ID")
    if not Path(".env").exists():
        raise SystemExit("Run python scripts/configure.py first")
    model = "data/synthetic-model.joblib"
    build_and_evaluate(model, "data/ml-evaluation.json")
    configure(".env", model, args.machine)
    print(
        f"Configured SYNTHETIC model for {args.machine}. Other .env settings preserved. Restart services."
    )
    print(
        f"python -m scripts.publish --profile synthetic --scenario subthreshold --machine {args.machine} --seconds 120"
    )


if __name__ == "__main__":
    main()
