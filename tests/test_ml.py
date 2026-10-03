import math
import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from edgeguard.api import create_app
from edgeguard.core import DEFAULT_LIMITS, SENSORS, Store
from edgeguard.model import Detector
from edgeguard.preprocessing import filter_sequence, filter_values
from edgeguard.synthetic import sequence
from edgeguard.training import train_artifact
from scripts.setup_ml import configure

KEY = "test-ml-key-not-for-deployment-123456"


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    directory = tmp_path_factory.mktemp("ml")
    path = directory / "model.joblib"
    data = train_artifact(
        sequence(1101, length=600),
        sequence(2202, length=300),
        path,
        "test generator",
        "synthetic",
    )
    return path, data


def test_threshold_comes_from_normal_calibration(artifact):
    path, data = artifact
    calibration = filter_sequence(sequence(2202, length=300))
    x = np.array([[r[s] for s in SENSORS] for r in calibration])
    expected = np.quantile(data["model"].score_samples(x), 0.005)
    assert data["threshold"] == pytest.approx(expected)
    result = Detector(path).evaluate(calibration[30])
    assert result["score"] == pytest.approx(result["raw_score"] - result["threshold"])
    assert result["source_type"] == "synthetic"
    assert math.isfinite(result["score"])


def test_runtime_and_offline_filter_match_with_gaps():
    rows = sequence(42, length=10)
    expected = filter_sequence(rows)
    previous = []
    for row, want in zip(rows, expected):
        assert filter_values(row["values"], row["timestamp"], previous) == want
        previous.insert(0, dict(row, quality={s: "VALID" for s in SENSORS}))
        previous = previous[:4]
    stale = dict(rows[0], quality={s: "VALID" for s in SENSORS})
    assert filter_values(rows[-1]["values"], 50, [stale]) == rows[-1]["values"]


def test_subthreshold_scenario_cannot_trigger_rules():
    for row in sequence(7777, "subthreshold"):
        assert all(
            value < DEFAULT_LIMITS[sensor][0] for sensor, value in row["values"].items()
        )


def test_model_integration_keeps_evidence_and_skips_missing(artifact, tmp_path):
    path, data = artifact
    store = Store(tmp_path / "edge.db")
    store.register("ML-01", "Test motor")
    detector = Detector(path)
    for i, row in enumerate(sequence(7777, "subthreshold", length=30, onset=5, end=25)):
        store.ingest(
            dict(
                machine_id="ML-01",
                message_id=str(i),
                timestamp=row["timestamp"],
                values=row["values"],
            ),
            detector,
            now=row["timestamp"],
        )
    incidents = store.snapshot()["incidents"]
    assert incidents and any(
        r["source"] == "model" for i in incidents for r in i["reasons"]
    )
    reason = next(r for i in incidents for r in i["reasons"] if r["source"] == "model")
    assert reason["source_type"] == "synthetic" and reason["model"] == data["version"]
    assert reason["signals"]
    values = sequence(42, length=1)[0]["values"]
    values["vibration"] = None
    result = store.ingest(
        dict(machine_id="ML-01", message_id="missing", timestamp=31, values=values),
        detector,
        now=31,
    )
    assert result["machine"]["latest"]["ml"]["status"] == "INSUFFICIENT_DATA"
    assert result["machine"]["latest"]["ml"]["source_type"] == "synthetic"


def test_legacy_artifact_requires_explicit_retraining(tmp_path):
    p = tmp_path / "legacy.joblib"
    joblib.dump({"features": list(SENSORS)}, p)
    with pytest.raises(ValueError, match="Retrain"):
        Detector(p)


def test_setup_preserves_credentials_and_fault_settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "EDGEGUARD_API_KEY=keep-this-secret\nEDGEGUARD_ENABLE_FAULTS=1\nEDGEGUARD_MODEL=old\n"
    )
    configure(env, "data/new.joblib", "ML-01")
    text = env.read_text()
    assert "EDGEGUARD_API_KEY=keep-this-secret" in text
    assert "EDGEGUARD_ENABLE_FAULTS=1" in text
    assert text.count("EDGEGUARD_MODEL=") == 1
    assert "EDGEGUARD_MODEL_MACHINE=ML-01" in text


def test_model_is_machine_bound_in_api(artifact, tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEGUARD_MODEL", str(artifact[0]))
    monkeypatch.setenv("EDGEGUARD_MODEL_MACHINE", "ML-01")
    app = create_app("edge", tmp_path / "edge.db", KEY, background=False)
    with TestClient(app) as client:
        h = {"X-API-Key": KEY}
        for name in ("ML-01", "OTHER"):
            client.post(
                "/api/machines", headers=h, json={"id": name, "label": name}
            ).raise_for_status()
            import time

            response = client.post(
                "/api/readings",
                headers=h,
                json=dict(
                    machine_id=name,
                    message_id=name,
                    timestamp=time.time(),
                    values=sequence(42, length=1)[0]["values"],
                ),
            )
            response.raise_for_status()
            status = response.json()["machine"]["latest"]["ml"]["status"]
            assert (
                status != "NOT_CALIBRATED"
                if name == "ML-01"
                else status == "NOT_CALIBRATED"
            )
        metadata = client.get("/api/state", headers=h).json()["model"]
        assert (
            metadata["version"] == artifact[1]["version"]
            and metadata["source_type"] == "synthetic"
        )
    monkeypatch.setenv("EDGEGUARD_MODEL", "nonexistent-file.joblib")
    cloud = create_app("cloud", tmp_path / "cloud.db", KEY, background=False)
    with TestClient(cloud) as client:
        assert (
            client.get("/api/state", headers={"X-API-Key": KEY}).json()["model"][
                "status"
            ]
            == "NOT_CALIBRATED"
        )
