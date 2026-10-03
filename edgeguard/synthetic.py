"""Explicitly synthetic 1 Hz motor features. Never present these as equipment measurements."""

import math
import random

SCENARIOS = (
    "normal",
    "noisy_normal",
    "missing",
    "critical",
    "subthreshold",
    "combination",
    "healthy_shift",
)


def sequence(seed, scenario="normal", length=150, onset=40, end=100):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    rng = random.Random(seed)
    phase = rng.uniform(0, 2 * math.pi)
    rows = []
    for t in range(length):
        load = 0.5 + 0.4 * math.sin(t / 45 + phase)
        v = dict(
            temperature=56 + 12 * load + rng.gauss(0, 0.6),
            vibration=1.9 + 1.1 * load + rng.gauss(0, 0.08),
            pressure=4.3 + 1.3 * load + rng.gauss(0, 0.05),
            current=6 + 5 * load + rng.gauss(0, 0.15),
            rpm=1430 + 140 * load + rng.gauss(0, 3),
        )
        abnormal = onset <= t < end and scenario in (
            "critical",
            "subthreshold",
            "combination",
        )
        if abnormal:
            if scenario == "critical":
                v["temperature"] = 106 + rng.gauss(0, 0.5)
                v["vibration"] = 10 + rng.gauss(0, 0.1)
            elif scenario == "subthreshold":
                v.update(
                    temperature=75 + rng.gauss(0, 0.2),
                    vibration=4 + rng.gauss(0, 0.04),
                    pressure=6.6 + rng.gauss(0, 0.03),
                    current=13 + rng.gauss(0, 0.1),
                    rpm=1670 + rng.gauss(0, 2),
                )
            else:
                # Each value is near a normal marginal range, but high temperature/vibration
                # accompanies low electrical current. IF may miss some such dependencies.
                v.update(
                    temperature=66.5 + rng.gauss(0, 0.2),
                    vibration=2.9 + rng.gauss(0, 0.04),
                    current=6.6 + rng.gauss(0, 0.1),
                )
        if scenario == "noisy_normal" and t % 13 == 0:
            v["temperature"] += rng.choice([-5, 5])
            v["vibration"] += rng.choice([-0.6, 0.6])
        if scenario == "missing" and onset <= t < end:
            v["vibration"] = None
        if scenario == "healthy_shift" and t >= onset:
            # Declared healthy new operating regime: robustness stress case, never used to tune.
            v["temperature"] += 4
            v["current"] += 1
        rows.append(
            dict(
                timestamp=float(t + 1),
                values={
                    s: round(x, 4) if x is not None else None for s, x in v.items()
                },
                abnormal=abnormal,
            )
        )
    return rows
