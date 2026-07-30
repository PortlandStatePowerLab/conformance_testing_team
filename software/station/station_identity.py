"""Resolve the active water-heater station from its configured hostname."""

from __future__ import annotations

import re
import socket
from pathlib import Path


STATION_HOST_PATTERN = re.compile(r"^WH-station([1-4])$", re.IGNORECASE)


def station_number(hostname: str | None = None) -> int:
    """Return station number 1-4 from a hostname such as ``WH-station2``."""
    active_hostname = hostname or socket.gethostname()
    match = STATION_HOST_PATTERN.fullmatch(active_hostname)
    if match is None:
        raise ValueError(
            "station hostname must be WH-station1, WH-station2, "
            f"WH-station3, or WH-station4; found {active_hostname!r}"
        )
    return int(match.group(1))


def station_results_directory(
    results_root: Path, hostname: str | None = None
) -> Path:
    """Return a station subdirectory, or the shared root for an unknown host."""
    try:
        number = station_number(hostname)
    except ValueError:
        return results_root
    return results_root / f"WH-{number}"
