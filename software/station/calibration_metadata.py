"""Build public calibration snapshots without private equipment identity."""

from __future__ import annotations

from typing import Any

SENSOR_FIELDS = frozenset({
    "manufacturer", "model_number", "year", "serial_number", "sensor",
    "sensor_manufacturer", "sensor_model_number", "sensor_model",
    "sensor_serial_number", "sensor_id",
})
TEMPERATURE_FIELDS = SENSOR_FIELDS | frozenset({
    "method", "correction_offset_f", "average_reference_temp_f",
    "average_uncalibrated_temp_f", "average_raw_counts", "reference_readings_f",
    "uncalibrated_readings_f", "raw_count_readings", "thermometer_used",
    "thermometer_accuracy_f", "last_cal_time",
})
PUBLIC_CALIBRATION_FIELDS = {
    "power": frozenset({
        "vrms_scale", "irms_scale", "vrms_offset", "irms_offset",
        "vrms_offset_volts", "irms_offset_amps", "last_cal_time",
        "line_vrms_used", "clamp_irms_used", "equipment_id", "sensor",
        "sensor_manufacturer", "sensor_model_number", "sensor_model", "sensor_serial_number",
    }),
    "hot_water_temp": TEMPERATURE_FIELDS,
    "cold_water_temp": TEMPERATURE_FIELDS,
    "flow_rate": SENSOR_FIELDS | frozenset({
        "method", "scale_gpm_per_count", "offset_gpm", "zero_raw_counts",
        "zero_raw_max_counts", "average_reference_gpm", "average_flowing_raw_counts",
        "average_uncalibrated_gpm", "zero_raw_count_readings",
        "zero_uncalibrated_gpm_readings", "reference_readings_gpm",
        "flowing_raw_count_averages", "uncalibrated_readings_gpm",
        "reference_device", "last_cal_time",
    }),
}


def public_calibration_snapshot(
    calibration: dict[str, Any], equipment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export known calibration fields and the run's anonymous equipment identity."""
    snapshot: dict[str, Any] = {}
    for section, fields in PUBLIC_CALIBRATION_FIELDS.items():
        if section not in calibration:
            continue
        values = calibration[section]
        if not isinstance(values, dict):
            raise ValueError(f"{section} calibration must contain an object")
        snapshot[section] = {key: value for key, value in values.items() if key in fields}
    # Older power-only configurations store coefficients at the top level.
    if "power" not in calibration:
        snapshot.update({key: value for key, value in calibration.items()
                         if key in PUBLIC_CALIBRATION_FIELDS["power"]})
    for field in ("equipment_id", "display_name"):
        if field in calibration:
            snapshot[field] = calibration[field]
    if equipment is not None:
        for field in ("equipment_id", "display_name"):
            snapshot[field] = equipment[field]
    return snapshot


def sanitize_station_calibration(calibration: dict[str, Any]) -> dict[str, Any]:
    """Remove legacy heater identity while preserving sensor metadata verbatim."""
    from copy import deepcopy

    result = deepcopy(calibration)
    heater_fields = {"manufacturer", "model_number", "year", "serial_number"}
    for field in heater_fields:
        result.pop(field, None)
    if isinstance(result.get("power"), dict):
        for field in heater_fields:
            result["power"].pop(field, None)
    return result
