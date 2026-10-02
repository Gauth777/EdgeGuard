"""Train from operator-approved normal CSV; no synthetic model is enabled by default."""

import argparse
import csv
import hashlib
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from edgeguard.core import SENSORS

p = argparse.ArgumentParser()
p.add_argument(
    "csv",
    help="Normal-operation CSV with temperature,vibration,pressure,current,rpm columns",
)
p.add_argument("--output", default="data/model.joblib")
a = p.parse_args()
with open(a.csv, newline="") as f:
    rows = list(csv.DictReader(f))
x = np.array([[float(r[s]) for s in SENSORS] for r in rows])
if len(x) < 200 or not np.isfinite(x).all():
    raise SystemExit("Need at least 200 complete finite normal samples")
# Final chronological 20% is held out; this is a normal false-positive check only.
cut = int(len(x) * 0.8)
model = IsolationForest(
    n_estimators=64, max_samples=256, contamination=0.01, random_state=42, n_jobs=1
).fit(x[:cut])
rate = float(np.mean(model.predict(x[cut:]) == -1))
version = hashlib.sha256(Path(a.csv).read_bytes()).hexdigest()[:12]
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
joblib.dump(
    dict(model=model, features=list(SENSORS), version=version, source=Path(a.csv).name),
    a.output,
)
print(
    {
        "model": a.output,
        "train_rows": cut,
        "held_out_normal_rows": len(x) - cut,
        "held_out_normal_alert_fraction": rate,
        "warning": "Not a failure recall estimate; validate on independent abnormal sequences before use",
    }
)
