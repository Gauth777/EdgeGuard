"""Trusted local model artifacts only: joblib loading can execute code."""

import math
import joblib
from .core import SENSORS


class Detector:
    def __init__(self, path):
        artifact = joblib.load(path)
        if artifact.get("schema") != 2 or artifact["features"] != list(SENSORS):
            raise ValueError(
                "Retrain with the current training script: model schema mismatch"
            )
        self.model = artifact["model"]
        self.version = artifact["version"]
        self.source = artifact["source"]
        self.source_type = artifact["source_type"]
        self.threshold = artifact["threshold"]
        self.reference = artifact["reference"]
        self.metadata = {
            k: v for k, v in artifact.items() if k not in ("model", "reference")
        }

    def evaluate(self, values):
        raw = float(self.model.score_samples([[values[s] for s in SENSORS]])[0])
        score = raw - self.threshold
        if not math.isfinite(score):
            raise ValueError("Model returned a nonfinite score")
        signals = []
        for sensor in SENSORS:
            low, high = self.reference[sensor]
            if not low <= values[sensor] <= high:
                signals.append(
                    dict(
                        sensor=sensor,
                        value=round(values[sensor], 3),
                        normal_low=round(low, 3),
                        normal_high=round(high, 3),
                    )
                )
        return dict(
            status="ANOMALY" if score < 0 else "NORMAL",
            score=score,
            raw_score=raw,
            threshold=self.threshold,
            model=self.version,
            source=self.source,
            source_type=self.source_type,
            signals=signals,
        )
