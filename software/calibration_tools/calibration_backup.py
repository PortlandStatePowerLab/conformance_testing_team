"""Shared retention behavior for station calibration backups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def replace_station_backup(
    calibration_path: Path,
    backup_path: Path,
) -> None:
    """Back up the current station file and retain only that new backup."""
    from software.station.calibration_metadata import sanitize_station_calibration

    original = json.loads(calibration_path.read_text(encoding="utf-8"))
    sanitized = sanitize_station_calibration(original)
    if sanitized == original:
        shutil.copy2(calibration_path, backup_path)
    else:
        backup_path.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    pattern = f"{calibration_path.stem}_*.json.save"
    for existing_backup in calibration_path.parent.glob(pattern):
        if existing_backup != backup_path:
            existing_backup.unlink()
