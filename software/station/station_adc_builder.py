"""
Construct the ADC installed by the active station hardware configuration.

The current station configuration uses a MAX1238EEE ADC. Future station configurations may
provide different ADC composition paths.
"""

# region Imports

# Library Imports

# Enables postponed evaluation of type annotations.
from __future__ import annotations

# Standard-library timing and static type-checking support.
from typing import TYPE_CHECKING

# Package Imports

# Physical station connection for the installed MAX1238.
from software.adc import build_max1238
from software.station.station_hardware_map import (
    MAX1238_I2C_ADDR,
    MAX1238_I2C_BUS,
)

if TYPE_CHECKING:
    from software.adc.max1238_driver import Max1238

# endregion Imports

# region MAX1238 Builder

def build_station_adc() -> Max1238:
    """Construct and configure the ADC installed on this station.

    Returns:
        Configured MAX1238 connected using the station hardware map.

    Ownership:
        The caller owns the returned ADC object and must close it when finished.

    Hardware:
        Calling this function opens the configured Raspberry Pi I2C bus and communicates
        with the physical MAX1238 device.

    Safety:
        This function accesses only the station ADC. It does not configure GPIO, actuate the valve,
        or access the ACS37800.
    """

    return build_max1238(
        bus_num=MAX1238_I2C_BUS,
        address=MAX1238_I2C_ADDR,
    )
# endregion MAX1238 Builder

# region <future ADC Builders>

# Add future station-specific ADC composition functions here.

# endregion <future ADC Builders>
