"""Shared time boundary for recorded commodity, power, and water measurements."""

import csv
from datetime import datetime
from pathlib import Path


def measurement_end_timestamp(directory, *fallbacks):
    """Return the latest valid recorded timestamp across all measurement streams.

    Use raw records, including draw completion rows, rather than plotted/smoothed
    samples. Synthetic flow boundaries and command shutdown events do not extend
    the measured experiment. Missing streams and malformed timestamps are skipped.
    """
    directory = Path(directory)
    latest = max(fallbacks) if fallbacks else None
    paths = [directory / "cta_commodity.csv", directory / "power.csv"]
    paths.extend(directory.glob("water_draw_*.csv"))
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                raw = (row.get("timestamp_pacific") or "").strip()
                try:
                    timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    continue
                if latest is None or timestamp > latest:
                    latest = timestamp
    if latest is None:
        raise ValueError(f"no recorded measurement timestamps found in {directory}")
    return latest
