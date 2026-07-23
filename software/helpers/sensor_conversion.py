"""Pure sensor conversions adapted from Blake's staged hardware repository."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class SensorConversionConfig:
    adc_reference_voltage_v: float = 4.096
    adc_code_count: int = 4096
    shunt_ohms: float = 120.0
    current_loop_min_ma: float = 4.0
    current_loop_max_ma: float = 20.0
    temperature_min_c: float = -50.0
    temperature_max_c: float = 150.0
    flow_min_gpm: float = 0.0
    flow_max_gpm: float = 10.0

    def __post_init__(self) -> None:
        if self.adc_reference_voltage_v <= 0 or self.adc_code_count <= 0:
            raise ValueError("ADC conversion configuration must be positive")
        if self.shunt_ohms <= 0:
            raise ValueError("shunt_ohms must be positive")
        if self.current_loop_max_ma <= self.current_loop_min_ma:
            raise ValueError("current loop maximum must exceed its minimum")
        if self.temperature_max_c <= self.temperature_min_c:
            raise ValueError("temperature maximum must exceed its minimum")
        if self.flow_max_gpm <= self.flow_min_gpm:
            raise ValueError("flow maximum must exceed its minimum")


NOMINAL_SENSOR_CONFIG = SensorConversionConfig()


def load_sensor_config(path: Path | None) -> SensorConversionConfig:
    if path is None:
        return NOMINAL_SENSOR_CONFIG
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("sensor calibration must be a JSON object")
    electrical = data.get("electrical", {})
    ranges = data.get("sensor_ranges", {})
    if not isinstance(electrical, dict) or not isinstance(ranges, dict):
        raise ValueError("sensor calibration sections must be JSON objects")
    return replace(
        NOMINAL_SENSOR_CONFIG,
        adc_reference_voltage_v=float(
            electrical.get(
                "adc_reference_voltage_v",
                NOMINAL_SENSOR_CONFIG.adc_reference_voltage_v,
            )
        ),
        shunt_ohms=float(
            electrical.get("shunt_ohms", NOMINAL_SENSOR_CONFIG.shunt_ohms)
        ),
        temperature_min_c=float(
            ranges.get("temperature_min_c", NOMINAL_SENSOR_CONFIG.temperature_min_c)
        ),
        temperature_max_c=float(
            ranges.get("temperature_max_c", NOMINAL_SENSOR_CONFIG.temperature_max_c)
        ),
        flow_min_gpm=float(
            ranges.get("flow_min_gpm", NOMINAL_SENSOR_CONFIG.flow_min_gpm)
        ),
        flow_max_gpm=float(
            ranges.get("flow_max_gpm", NOMINAL_SENSOR_CONFIG.flow_max_gpm)
        ),
    )


def counts_to_voltage(raw_counts: int, config: SensorConversionConfig) -> float:
    if not 0 <= raw_counts < config.adc_code_count:
        raise ValueError("ADC count is outside the configured range")
    return raw_counts / config.adc_code_count * config.adc_reference_voltage_v


def loop_value(
    voltage: float,
    minimum: float,
    maximum: float,
    config: SensorConversionConfig,
) -> float:
    current_ma = max(voltage / config.shunt_ohms, 0.0) * 1000.0
    normalized = (current_ma - config.current_loop_min_ma) / (
        config.current_loop_max_ma - config.current_loop_min_ma
    )
    return minimum + normalized * (maximum - minimum)


def celsius_to_fahrenheit(value: float) -> float:
    return value * 9.0 / 5.0 + 32.0
