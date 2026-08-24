"""Resolve stable station equipment identity for reports and plots."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


EQUIPMENT_DIRECTORY = Path(__file__).resolve().parents[1] / "saved_data" / "equipment"
SNAPSHOT_FILENAME = "equipment.json"
STATION_FOLDER = re.compile(r"^WH[-_](\d+)$", re.IGNORECASE)


def _station_number(run_directory: Path, equipment: dict[str, Any] | None = None) -> int | None:
    if equipment:
        match = re.fullmatch(
            r"WH[-_]?station[-_]?(\d+)",
            str(equipment.get("station_id", "")),
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))
    for part in reversed(run_directory.parts):
        match = STATION_FOLDER.fullmatch(part)
        if match:
            return int(match.group(1))
    return None


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if not str(value.get("manufacturer", "")).strip() or not str(
        value.get("model_number", "")
    ).strip():
        return None
    return value


def load_run_equipment(run_directory: Path | str) -> tuple[int | None, dict[str, Any] | None]:
    """Load a run snapshot, falling back to current station equipment."""
    directory = Path(run_directory).resolve()
    snapshot = _load(directory / SNAPSHOT_FILENAME)
    number = _station_number(directory, snapshot)
    if snapshot is not None:
        return number, snapshot
    if number is None:
        return None, None
    current = _load(EQUIPMENT_DIRECTORY / f"WH-station{number}.json")
    return number, current


def equipment_title_line(run_directory: Path | str) -> str | None:
    """Return ``WH-N — Manufacturer Model`` when equipment is available."""
    number, equipment = load_run_equipment(run_directory)
    if equipment is None:
        return f"WH-{number}" if number is not None else None
    identity = f"{equipment['manufacturer']} {equipment['model_number']}"
    return f"WH-{number} — {identity}" if number is not None else identity

