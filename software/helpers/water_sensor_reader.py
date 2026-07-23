"""Grouped water-draw sensor acquisition adapted from Blake's sensor services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:
    from .hardware_map import CH_AMBIENT, CH_COLD, CH_FLOW, CH_HOT
    from .sensor_conversion import (
        SensorConversionConfig,
        celsius_to_fahrenheit,
        counts_to_voltage,
        load_sensor_config,
        loop_value,
    )
except ImportError:
    from helpers.hardware_map import CH_AMBIENT, CH_COLD, CH_FLOW, CH_HOT
    from helpers.sensor_conversion import (
        SensorConversionConfig,
        celsius_to_fahrenheit,
        counts_to_voltage,
        load_sensor_config,
        loop_value,
    )


class SensorAdc(Protocol):
    def read_range(self, start_channel: int, end_channel: int) -> dict[int, int]: ...


@dataclass(frozen=True)
class WaterSensorSnapshot:
    hot_raw_counts: int
    cold_raw_counts: int
    flow_raw_counts: int
    ambient_raw_counts: int
    hot_temp_c: float
    hot_temp_f: float
    cold_temp_c: float
    cold_temp_f: float
    ambient_temp_c: float
    ambient_temp_f: float
    flow_gpm: float


class WaterSensorReader:
    def __init__(
        self, adc: SensorAdc, *, calibration_path: Path | None = None
    ) -> None:
        self._adc = adc
        self._config: SensorConversionConfig = load_sensor_config(calibration_path)

    def snapshot(self) -> WaterSensorSnapshot:
        counts = self._adc.read_range(CH_HOT, CH_AMBIENT)
        required = (CH_HOT, CH_COLD, CH_FLOW, CH_AMBIENT)
        missing = [channel for channel in required if channel not in counts]
        if missing:
            raise RuntimeError(f"ADC scan omitted channels: {missing}")

        hot_raw = counts[CH_HOT]
        cold_raw = counts[CH_COLD]
        flow_raw = counts[CH_FLOW]
        ambient_raw = counts[CH_AMBIENT]
        hot_voltage = counts_to_voltage(hot_raw, self._config)
        cold_voltage = counts_to_voltage(cold_raw, self._config)
        flow_voltage = counts_to_voltage(flow_raw, self._config)
        ambient_voltage = counts_to_voltage(ambient_raw, self._config)
        hot_c = loop_value(
            hot_voltage,
            self._config.temperature_min_c,
            self._config.temperature_max_c,
            self._config,
        )
        cold_c = loop_value(
            cold_voltage,
            self._config.temperature_min_c,
            self._config.temperature_max_c,
            self._config,
        )
        ambient_c = ambient_voltage * 100.0
        return WaterSensorSnapshot(
            hot_raw_counts=hot_raw,
            cold_raw_counts=cold_raw,
            flow_raw_counts=flow_raw,
            ambient_raw_counts=ambient_raw,
            hot_temp_c=hot_c,
            hot_temp_f=celsius_to_fahrenheit(hot_c),
            cold_temp_c=cold_c,
            cold_temp_f=celsius_to_fahrenheit(cold_c),
            ambient_temp_c=ambient_c,
            ambient_temp_f=celsius_to_fahrenheit(ambient_c),
            flow_gpm=loop_value(
                flow_voltage,
                self._config.flow_min_gpm,
                self._config.flow_max_gpm,
                self._config,
            ),
        )
