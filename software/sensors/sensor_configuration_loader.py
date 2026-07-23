"""Load and validate optional WH1 sensor-conversion overrides."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from software.sensors.sensor_conversion_math import (
    NOMINAL_SENSOR_CONFIG,
    SensorConversionConfig,
)


def load_sensor_conversion_config(
    calibration_path: Path | None,
) -> SensorConversionConfig:
    """Load optional calibration overrides onto the nominal configuration."""
    if calibration_path is None:
        return NOMINAL_SENSOR_CONFIG

    if not calibration_path.exists():
        raise FileNotFoundError(
            f"Calibration file does not exist: {calibration_path}"
        )

    calibration_data = json.loads(calibration_path.read_text(encoding="utf-8"))
    if not isinstance(calibration_data, dict):
        raise ValueError("calibration data must be a JSON object")

    electrical_overrides = calibration_data.get("electrical", {})
    sensor_overrides = calibration_data.get("sensor_ranges", {})

    if not isinstance(electrical_overrides, dict):
        raise ValueError("electrical calibration data must be a JSON object")
    if not isinstance(sensor_overrides, dict):
        raise ValueError("sensor_ranges calibration data must be a JSON object")

    return replace(
        NOMINAL_SENSOR_CONFIG,
        adc_reference_voltage_v=float(
            electrical_overrides.get(
                "adc_reference_voltage_v",
                NOMINAL_SENSOR_CONFIG.adc_reference_voltage_v,
            )
        ),
        shunt_ohms=float(
            electrical_overrides.get(
                "shunt_ohms",
                NOMINAL_SENSOR_CONFIG.shunt_ohms,
            )
        ),
        temperature_min_c=float(
            sensor_overrides.get(
                "temperature_min_c",
                NOMINAL_SENSOR_CONFIG.temperature_min_c,
            )
        ),
        temperature_max_c=float(
            sensor_overrides.get(
                "temperature_max_c",
                NOMINAL_SENSOR_CONFIG.temperature_max_c,
            )
        ),
        flow_min_gpm=float(
            sensor_overrides.get(
                "flow_min_gpm",
                NOMINAL_SENSOR_CONFIG.flow_min_gpm,
            )
        ),
        flow_max_gpm=float(
            sensor_overrides.get(
                "flow_max_gpm",
                NOMINAL_SENSOR_CONFIG.flow_max_gpm,
            )
        ),
    )
