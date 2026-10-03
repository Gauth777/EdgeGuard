"""Chronological normal-data fit/calibration/holdout. Run as python -m scripts.train."""

import argparse
import csv
import json
import math
from pathlib import Path
from edgeguard.core import SENSORS, RANGES
from edgeguard.model import Detector
from edgeguard.preprocessing import filter_sequence
from edgeguard.training import train_artifact


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "csv",
        help="Operator-selected normal rows; optional monotonic timestamp column (otherwise assume 1 Hz)",
    )
    p.add_argument("--output", default="data/model.joblib")
    args = p.parse_args()
    with open(args.csv, newline="") as f:
        raw = list(csv.DictReader(f))
    rows = []
    for j, row in enumerate(raw):
        values = {s: float(row[s]) for s in SENSORS}
        ts = float(row.get("timestamp", j + 1))
        if not math.isfinite(ts) or any(
            not math.isfinite(v) or not RANGES[s][0] <= v <= RANGES[s][1]
            for s, v in values.items()
        ):
            raise ValueError(f"Invalid normal sample at CSV row {j + 2}")
        if rows and ts <= rows[-1]["timestamp"]:
            raise ValueError("CSV timestamps must strictly increase")
        rows.append(dict(timestamp=ts, values=values))
    if len(rows) < 600:
        raise ValueError(
            "Supply at least 600 complete normal rows for 60/20/20 splitting"
        )
    a, b = int(len(rows) * 0.6), int(len(rows) * 0.8)
    artifact = train_artifact(rows[:a], rows[a:b], args.output, Path(args.csv).name)
    detector = Detector(args.output)
    held_out = filter_sequence(rows[b:])
    flags = [detector.evaluate(v)["status"] == "ANOMALY" for v in held_out]
    result = dict(
        model=args.output,
        version=artifact["version"],
        training_rows=a,
        calibration_rows=b - a,
        held_out_normal_rows=len(flags),
        held_out_normal_flag_fraction=sum(flags) / len(flags),
        source_type="operator_selected",
        note="Normal-only check; this is not anomaly recall or industrial validation. Test independent failure sequences.",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
