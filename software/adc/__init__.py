"""Public API for analog-to-digital converter (ADC) abstractions."""

from .adc_interfaces import SensorAdc
from .max1238_builder import build_max1238

__all__ = [
    "SensorAdc",
    "build_max1238"
]
