"""Shared retention behavior for station calibration backups."""

from __future__ import annotations

import shutil
from pathlib import Path


def replace_station_backup(
    calibration_path: Path,
    backup_path: Path,
) -> None:
    """Back up the current station file and retain only that new backup."""
    shutil.copy2(calibration_path, backup_path)
    pattern = f"{calibration_path.stem}_*.json.save"
    for existing_backup in calibration_path.parent.glob(pattern):
        if existing_backup != backup_path:
            existing_backup.unlink()
