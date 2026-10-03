"""One causal filter shared by runtime, training and evaluation."""

import statistics
from .core import SENSORS


def filter_values(values, timestamp, previous):
    # previous is newest first, exactly as returned by the runtime history query.
    return {
        sensor: statistics.median(
            [values[sensor]]
            + [
                row["values"][sensor]
                for row in previous[:4]
                if row["quality"].get(sensor) == "VALID"
                and 0 <= timestamp - row["timestamp"] <= 10
            ]
        )
        for sensor in SENSORS
    }


def filter_sequence(rows):
    """Complete normal training rows only; reset history between independent runs."""
    previous = []
    result = []
    for row in rows:
        result.append(filter_values(row["values"], row["timestamp"], previous))
        previous.insert(0, dict(row, quality={s: "VALID" for s in SENSORS}))
        previous = previous[:4]
    return result
