"""Load water-temperature and flow corrections from a station calibration document."""

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


def _load_temperature_offset_f(
    calibration_path: Path | None,
    section_name: str,
) -> float:
    if calibration_path is None:
        return 0.0
    if not calibration_path.is_file():
        raise FileNotFoundError(calibration_path)
    document = json.loads(calibration_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("station calibration JSON must contain an object")
    section = document.get(section_name)
    if section is None:
        return 0.0
    if not isinstance(section, dict):
        raise ValueError(f"{section_name} calibration must contain an object")
    value = section.get("correction_offset_f", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{section_name}.correction_offset_f must be a number")
    offset = float(value)
    if not math.isfinite(offset):
        raise ValueError(f"{section_name}.correction_offset_f must be finite")
    return offset


def load_hot_water_offset_f(calibration_path: Path | None) -> float:
    """Return a finite hot-water Fahrenheit correction, defaulting to zero."""
    return _load_temperature_offset_f(calibration_path, "hot_water_temp")


def load_cold_water_offset_f(calibration_path: Path | None) -> float:
    """Return a finite cold-water Fahrenheit correction, defaulting to zero."""
    return _load_temperature_offset_f(calibration_path, "cold_water_temp")


def load_flow_calibration(
    calibration_path: Path | None,
) -> tuple[float, float] | None:
    """Return the raw-count flow scale and intercept, or no calibration."""
    if calibration_path is None:
        return None
    if not calibration_path.is_file():
        raise FileNotFoundError(calibration_path)
    document = json.loads(calibration_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("station calibration JSON must contain an object")
    section = document.get("flow_rate")
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("flow_rate calibration must contain an object")

    values: dict[str, float] = {}
    for name in ("scale_gpm_per_count", "offset_gpm"):
        value = section.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"flow_rate.{name} must be a number")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError(f"flow_rate.{name} must be finite")
        values[name] = converted
    if values["scale_gpm_per_count"] <= 0.0:
        raise ValueError("flow_rate.scale_gpm_per_count must be greater than zero")
    return values["scale_gpm_per_count"], values["offset_gpm"]
