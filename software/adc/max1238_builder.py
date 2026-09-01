"""
Construct and configure a MAX1238 ADC.

This module owns the concrete MAX1238 construction and startup boundary. It opens the
caller-selected Linux I2C bus, configures the MAX1238 with its internal 4.096 V reference
and external conversion clock, waits for the internal reference to become ready, and returns
the prepared driver.

Station-specific connection details such as I2C bus number and installed address belong
to the station composition layer. Higher-level sensor services should depend on the shared
ADC interface instead of importing the concrete driver.
"""

# region Imports

# Enables postponed evaluation of type annotations.
from __future__ import annotations

# Standard-library timing and static type-checking support.
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Imported only by static type checkers. The real hardware import remains inside the
    # build_max1238() function, so this module can be imported on Windows.
    from software.adc.max1238_driver import Max1238

# endregion Imports

# region MAX1238 Device Defaults

# Default seven-bit I2C address for the MAX1238EEE+ device.
MAX1238_DEFAULT_I2C_ADDRESS = 0x35

# endregion MAX1238 Device Defaults

# region MAX1238 Startup Configuration

# The internal voltage reference requires 10 ms to become ready.
MAX1238_INTERNAL_REFERENCE_WAKEUP_S = 0.010

# endregion MAX1238 Startup Configuration

# region ADC Builder

def build_max1238(
    *,
    bus_num: int,
    address: int = MAX1238_DEFAULT_I2C_ADDRESS,
) -> Max1238:
    """Construct and configure one ready-to-use MAX1238 ADC.

    Args:
        bus_num (int): Linux I2C bus number. Contains physical MAX1238.
            Caller or station composition layer must supply this value.
        address (int): Seven-bit MAX1238 I2C address. Defaults to MAX1238 device address.

    Returns:
        A configured ``Max1238`` object with an open SMBus connection.

    Raises:
        ImportError: If the Linux ``smbus2`` dependency is unavailable.

        OSError: If the requested I2C bus cannot be opened, the MAX1238 does not
            acknowledge, or setup communication fails.

        Exception: Any other construction or device-setup failure is allowed to
            propagate to the caller.

    Configuration:
        Configures the MAX1238 with its internal 4.096 V reference, external
        conversion clock, unipolar input mode, and single-ended channel reads.

    Ownership:
        The caller owns the returned ADC object and must call ``close()`` when the
        surrounding diagnostic or runtime process is finished.

    Timing:
        The builder waits for the internal voltage reference after transmitting
        the setup byte. It does not perform a sensor conversion.

    Safety:
        This function accesses only the ADC I2C device. It does not configure
        GPIO, actuate the valve, or access the ACS37800.
    """
    # Keeps the Linux-only hardware dependency out of Windows import paths.
    from software.adc.max1238_driver import (
        ClockType,
        Max1238,
        Polarity,
        ReferenceVoltage,
        ResetMode,
    )

    adc: Max1238 | None = None

    try:
        # Opening the concrete driver also opens the selected SMBus connection.
        adc = Max1238(
            address=address,
            bus_num=bus_num,
        )

        # Configures the internal 4.096 V reference and external conversion clock
        # explicitly instead of relying on hidden concrete-driver defaults.
        adc.setup_adc(
            referenceVoltage=ReferenceVoltage.InternalRef_AlwaysON_AnalogIn,
            clock=ClockType.External,
            polarity=Polarity.Unipolar,
            reset=ResetMode.NoAction,
        )

        # Allows the internal reference to stabilize before exposing the ADC to
        # sensor services.
        time.sleep(MAX1238_INTERNAL_REFERENCE_WAKEUP_S)

        return adc

    except BaseException:
        # Attempts cleanup without replacing the original construction or setup error.
        if adc is not None:
            try:
                adc.close()
            except BaseException:
                pass
        raise

# endregion MAX1238 Builder
