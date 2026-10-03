"""Reproducible synthetic benchmark through the actual Store.ingest decision path."""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from edgeguard.core import Store
from edgeguard.model import Detector
from edgeguard.synthetic import SCENARIOS, sequence
from edgeguard.training import train_artifact


def build_and_evaluate(
    output="data/synthetic-model.joblib", report="data/ml-evaluation.json"
):
    # Fixed before evaluation. All calibration data is normal. No test-based tuning.
    train = sequence(1101, length=2400)
    calibration = sequence(2202, length=1200)
    artifact = train_artifact(
        train,
        calibration,
        output,
        "EdgeGuard synthetic motor generator v1",
        source_type="synthetic",
    )
    detector = Detector(output)
    results = []
    latency = []
    with tempfile.TemporaryDirectory() as directory:
        for scenario in SCENARIOS:
            for seed in (3303, 4404, 5505, 6606):
                rows = sequence(seed, scenario)
                for policy in ("rules", "hybrid"):
                    store = Store(Path(directory) / f"{scenario}-{seed}-{policy}.db")
                    store.register("EVAL", "Evaluation motor")
                    for t, row in enumerate(rows):
                        message = dict(
                            machine_id="EVAL",
                            message_id=f"{t}",
                            timestamp=row["timestamp"],
                            values=row["values"],
                        )
                        begin = time.perf_counter()
                        store.ingest(
                            message,
                            detector if policy == "hybrid" else None,
                            now=row["timestamp"],
                        )
                        if policy == "hybrid":
                            latency.append((time.perf_counter() - begin) * 1000)
                    state = store.snapshot()
                    events = [
                        event["at"]
                        for incident in state["incidents"]
                        for event in incident["timeline"]
                        if event["action"]
                        in ("Incident opened", "Abnormal behaviour resumed")
                    ]
                    onset = 41
                    end = 101
                    fault = scenario in ("critical", "subthreshold", "combination")
                    detections = (
                        [at for at in events if onset <= at < end] if fault else []
                    )
                    false_events = [
                        at for at in events if not fault or at < onset or at >= end
                    ]
                    results.append(
                        dict(
                            scenario=scenario,
                            seed=seed,
                            policy=policy,
                            abnormal_episode=fault,
                            detected=bool(detections) if fault else None,
                            delay_seconds=min(detections) - onset
                            if detections
                            else None,
                            false_incident_starts=len(false_events),
                            incident_starts=len(events),
                        )
                    )
            print(f"Evaluated {scenario}", flush=True)
    summary = []
    for scenario in SCENARIOS:
        for policy in ("rules", "hybrid"):
            group = [
                r
                for r in results
                if r["scenario"] == scenario and r["policy"] == policy
            ]
            delays = [
                r["delay_seconds"] for r in group if r["delay_seconds"] is not None
            ]
            summary.append(
                dict(
                    scenario=scenario,
                    policy=policy,
                    sequences=len(group),
                    abnormal_episodes=sum(r["abnormal_episode"] for r in group),
                    detected_episodes=sum(r["detected"] is True for r in group),
                    false_incident_starts=sum(
                        r["false_incident_starts"] for r in group
                    ),
                    median_detection_delay_seconds=statistics.median(delays)
                    if delays
                    else None,
                )
            )
    result = dict(
        source_type="synthetic",
        model_version=artifact["version"],
        train_seed=1101,
        calibration_seed=2202,
        evaluation_seeds=[3303, 4404, 5505, 6606],
        training_rows=2400,
        calibration_rows=1200,
        threshold=artifact["threshold"],
        normal_tail=artifact["normal_tail"],
        sequence_seconds=150,
        summary=summary,
        per_sequence=results,
        hybrid_ingestion_ms=dict(
            median=statistics.median(latency),
            p95=sorted(latency)[int(0.95 * (len(latency) - 1))],
        ),
        artifact_bytes=Path(output).stat().st_size,
        limitations=[
            "Synthetic scenarios, not industrial accuracy.",
            "Same generator family in training and evaluation; held-out seeds do not eliminate simulation bias.",
            "Healthy-shift scenario tests a new valid regime and may cause false alarms.",
            "Only four runs per scenario; no fleet throughput claim.",
            "Latency includes SQLite and inference on the current host; not a target-device benchmark.",
        ],
    )
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"model": output, "report": report, "summary": summary}, indent=2))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/synthetic-model.joblib")
    p.add_argument("--report", default="data/ml-evaluation.json")
    a = p.parse_args()
    build_and_evaluate(a.output, a.report)
