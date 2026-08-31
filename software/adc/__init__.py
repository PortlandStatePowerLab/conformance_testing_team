"""Public API for analog-to-digital converter (ADC) abstractions."""

# This __init__ will serve as a sub-package API for the consumers that require
# analog-to-digital (ADC) conversion services.
#
# Public bounds:
#
# - SensorAdc protocol from `software/adc/adc_interfaces.py`
# - `build_max1238()` function from `software/adc/max1238_builder.py`
#
# Private bounds:
#
# - Max1238 driver class from `software/adc/max1238_driver.py`
# - `MAX1238` register and command-byte implementation details
# - Reference-voltage, clock, polarity, and reset configuration choices
# - Internal-reference startup delay
# - I2C bus number and MAX1238 device address
# - Station hardware mapping
# - ADC diagnostic functions intended for developing or troubleshooting, not
#   standard runtime operation
# - Legacy ADC implementations

from .adc_interfaces import SensorAdc
from .max1238_builder import build_max1238

__all__ = [
    "SensorAdc",
    "build_max1238"
]
