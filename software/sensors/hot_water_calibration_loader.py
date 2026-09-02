"""Load the hot-water offset from a station calibration document."""

from __future__ import annotations

import json
import math
from pathlib import Path


DEFAULT_CALIBRATION_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "saved_data" / "calibration"
)


def station_calibration_path(station_number: int) -> Path:
    """Return the standard calibration path for one station number."""
    if station_number not in (1, 2, 3, 4):
        raise ValueError(f"unsupported station number: {station_number}")
    return DEFAULT_CALIBRATION_DIRECTORY / f"WH-station{station_number}.json"


def load_hot_water_offset_f(calibration_path: Path | None) -> float:
    """Return a finite hot-water Fahrenheit correction, defaulting to zero."""
    if calibration_path is None:
        return 0.0
    if not calibration_path.is_file():
        raise FileNotFoundError(calibration_path)
    document = json.loads(calibration_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("station calibration JSON must contain an object")
    section = document.get("hot_water_temp")
    if section is None:
        return 0.0
    if not isinstance(section, dict):
        raise ValueError("hot_water_temp calibration must contain an object")
    value = section.get("correction_offset_f", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("hot_water_temp.correction_offset_f must be a number")
    offset = float(value)
    if not math.isfinite(offset):
        raise ValueError("hot_water_temp.correction_offset_f must be finite")
    return offset
