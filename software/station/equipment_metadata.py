"""Resolve stable station equipment identity for reports and plots."""

from __future__ import annotations

import json
import re
import math
from pathlib import Path
from typing import Any


EQUIPMENT_DIRECTORY = Path(__file__).resolve().parents[2] / "saved_data" / "equipment"
PRIVATE_EQUIPMENT_DIRECTORY = EQUIPMENT_DIRECTORY.parent / "private" / "equipment"
PUBLIC_EQUIPMENT_FIELDS = (
    "equipment_id", "display_name", "date_added", "capacity_gallons", "temperature_setpoint_f",
)
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
    """Return the anonymous heater display name for plots and reports."""
    number, equipment = load_run_equipment(run_directory)
    if equipment is not None:
        name = str(equipment.get("display_name", "")).strip()
        if name:
            return name
    if number is not None:
        current = _load(EQUIPMENT_DIRECTORY / f"WH-station{number}.json")
        # Legacy snapshots predate display_name. Use the configured name unless
        # their permanent ID proves that the station now holds another heater.
        if current is not None:
            archived_id = (equipment or {}).get("equipment_id")
            current_id = current.get("equipment_id")
            name = str(current.get("display_name", "")).strip()
            if name and (not archived_id or archived_id == current_id):
                return name
    return f"HPWH-{number}" if number is not None else None


def public_equipment_record(equipment: dict[str, Any]) -> dict[str, Any]:
    """Select the anonymous fields from the private source of truth."""
    missing = set(PUBLIC_EQUIPMENT_FIELDS).difference(equipment)
    if missing:
        raise ValueError(f"Equipment configuration missing fields: {', '.join(sorted(missing))}")
    for field in ("equipment_id", "display_name", "date_added"):
        if not isinstance(equipment[field], str) or not equipment[field].strip():
            raise ValueError(f"Equipment {field} must be a nonempty string")
    for field in ("capacity_gallons", "temperature_setpoint_f"):
        value = equipment[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Equipment {field} must be a finite number")
    if equipment["capacity_gallons"] <= 0:
        raise ValueError("Equipment capacity_gallons must be positive")
    return {field: equipment[field] for field in PUBLIC_EQUIPMENT_FIELDS}


def generate_public_equipment(
    private_path: Path, public_directory: Path = EQUIPMENT_DIRECTORY,
) -> dict[str, Any]:
    """Refresh a public record from its private source without changing its ID."""
    equipment = json.loads(private_path.read_text(encoding="utf-8"))
    snapshot = public_equipment_record(equipment)
    public_directory.mkdir(parents=True, exist_ok=True)
    destination = public_directory / private_path.name
    # Avoid partially written JSON if the GUI and runner refresh concurrently.
    import os
    import tempfile

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=public_directory,
                                         prefix=".equipment-", suffix=".tmp", delete=False) as output:
            temporary_path = Path(output.name)
            json.dump(snapshot, output, indent=2)
            output.write("\n")
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return snapshot


def main() -> None:
    """Regenerate public equipment records after editing private station data."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--private-directory", type=Path, default=PRIVATE_EQUIPMENT_DIRECTORY)
    parser.add_argument("--public-directory", type=Path, default=EQUIPMENT_DIRECTORY)
    args = parser.parse_args()
    paths = sorted(args.private_directory.glob("WH-station*.json"))
    if not paths:
        parser.error(f"No private equipment records found in {args.private_directory}")
    for path in paths:
        generate_public_equipment(path, args.public_directory)
        print(f"Generated {path.name}")


if __name__ == "__main__":
    main()
