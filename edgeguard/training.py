"""Fit only normal training rows; choose threshold only on separate normal calibration."""

import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from .core import SENSORS
from .preprocessing import filter_sequence


def train_artifact(
    train,
    calibration,
    output,
    source,
    source_type="operator_selected",
    normal_tail=0.005,
):
    if len(train) < 200 or len(calibration) < 100:
        raise ValueError("Need at least 200 training and 100 calibration rows")
    if not 0 < normal_tail < 0.1:
        raise ValueError("normal_tail must be between 0 and 0.1")
    filtered_train = filter_sequence(train)
    filtered_calibration = filter_sequence(calibration)
    x = np.array([[row[s] for s in SENSORS] for row in filtered_train])
    cal = np.array([[row[s] for s in SENSORS] for row in filtered_calibration])
    if not np.isfinite(x).all() or not np.isfinite(cal).all():
        raise ValueError("Training/calibration contain invalid values")
    model = IsolationForest(
        n_estimators=64,
        max_samples=256,
        contamination="auto",
        random_state=42,
        n_jobs=1,
    ).fit(x)
    threshold = float(np.quantile(model.score_samples(cal), normal_tail))
    configuration = dict(
        features=list(SENSORS),
        trees=64,
        max_samples=256,
        seed=42,
        filter="causal-median-5-with-10s-max-age",
        normal_tail=normal_tail,
        source_type=source_type,
    )
    digest = hashlib.sha256(
        x.tobytes() + cal.tobytes() + json.dumps(configuration, sort_keys=True).encode()
    ).hexdigest()[:16]
    artifact = dict(
        schema=2,
        model=model,
        features=list(SENSORS),
        version=digest,
        source=source,
        source_type=source_type,
        threshold=threshold,
        train_rows=len(x),
        calibration_rows=len(cal),
        normal_tail=normal_tail,
        filter=configuration["filter"],
        reference={
            s: [float(np.quantile(x[:, j], 0.01)), float(np.quantile(x[:, j], 0.99))]
            for j, s in enumerate(SENSORS)
        },
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return artifact
