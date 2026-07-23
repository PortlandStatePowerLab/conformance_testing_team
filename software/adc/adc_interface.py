"""Shared ADC interfaces for hardware-agnostic station services.

This module defines the minimal raw-read operations required by sensor services.
It contains no concrete ADC driver, I2C configuration, device setup, resource
ownership, or shutdown behavior.
"""

# region Imports

# Enables postponed evaluation of type annotations.
from __future__ import annotations

# Structural interface support from the Python standard library.
from typing import Protocol

# endregion Imports

# region ADC Interfaces

class SensorAdc(Protocol):
    """Define the raw ADC operations required by station sensor services.

    Concrete hardware selection, device setup, bus ownership, and cleanup
    intentionally remain outside this interface.
    """

    def read_single(self, channel: int, /) -> int | None:
        """Read one ADC channel.

        Args:
            channel (int): Analog input channel number.

        Returns:
            Raw ADC result in counts, or ``None`` when an implementation cannot provide
            a valid reading.

        Safety:
            This operation must not actuate station outputs.
        """
        ...

    def read_range(
        self,
        first_channel: int,
        last_channel: int,
        /,
    ) -> dict[int, int]:
        """Read a sequential range of ADC channels.

        Args:
            first_channel (int): First analog input channel to include.
            last_channel (int): Last analog input channel to include.

        Returns:
            Mapping from channel number to raw ADC counts.

        Timing:
            Channel results are sequential rather than simultaneous.

        Safety:
            This operation must not actuate station outputs.
        """
        ...

# endregion ADC Interfaces
