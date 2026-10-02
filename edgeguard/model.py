"""Load only locally trained, trusted artifacts: joblib files can execute code."""

import joblib
from .core import SENSORS


class Detector:
    def __init__(self, path):
        artifact = joblib.load(path)
        if artifact["features"] != list(SENSORS):
            raise ValueError("Model feature schema mismatch")
        self.model = artifact["model"]
        self.version = artifact["version"]
        self.source = artifact["source"]

    def evaluate(self, values):
        score = float(self.model.decision_function([[values[s] for s in SENSORS]])[0])
        return dict(
            status="ANOMALY" if score < 0 else "NORMAL",
            score=score,
            model=self.version,
            source=self.source,
        )
