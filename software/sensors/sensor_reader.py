"""Hardware-agnostic sensor services for the water-heater test station.

This module reads an injected station ADC through the minimal ``SensorAdc``
interface and applies the pure sensor-conversion functions. It requests an
effective configuration from the sensor configuration loader and caches the
corresponding temperature and flow spans.

The module does not construct, configure, own, or close hardware. It also does
not control valves, schedule draws, print results, or write CSV files.
"""

# region Imports

# Enables postponed evaluation of type annotations as a Python language feature.
from __future__ import annotations

# Standard-library helpers for immutable sensor snapshots and paths.
from dataclasses import dataclass
from pathlib import Path

# Station sensor-channel assignments.
from software.station.station_hardware_map import (
    CH_AMBIENT,
    CH_COLD,
    CH_FLOW,
    CH_HOT,
)

# Sensor-conversion configuration and pure conversion helpers.
from software.sensors.sensor_conversion_math import (
    adc_counts_to_voltage,
    lm35_voltage_to_temp_c,
    lm35_voltage_to_temp_f,
    voltage_to_linear_loop_value,
)

# Shared hardware-agnostic ADC read interface from ``adc_interface.py``.
from software.adc.adc_interface import SensorAdc
from software.sensors.sensor_configuration_loader import (
    load_sensor_conversion_config,
)

# endregion Imports

# region Sensor Data

# Stores raw ADC counts and converted measurements from one grouped sensor scan.
@dataclass(frozen=True)
class SensorSnapshot:
    """Store raw and converted readings from one grouped sensor scan.

    Attributes:
        hot_raw_counts (int): Raw ADC counts for the hot-water transmitter.
        cold_raw_counts (int): Raw ADC counts for the cold-water transmitter.
        flow_raw_counts (int): Raw ADC counts for the flow transmitter.
        ambient_raw_counts (int): Raw ADC counts for the ambient sensor.
        hot_temp_c (float): Hot-water transmitter temperature in degrees Celsius.
        hot_temp_f (float): Hot-water transmitter temperature in degrees Fahrenheit.
        cold_temp_c (float): Cold-water transmitter temperature in degrees Celsius.
        cold_temp_f (float): Cold-water transmitter temperature in degrees Fahrenheit.
        ambient_temp_c (float): LM35 ambient temperature in degrees Celsius.
        ambient_temp_f (float): LM35 ambient temperature in degrees Fahrenheit.
        flow_gpm (float): Flow transmitter reading in gallons per minute.

    Timing:
        Values are read sequentially during one ADC scan and are not physically
        simultaneous.
    """
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

# endregion Sensor Data

# region Scanned-Channel Lookup

# Returns one validated sensor ``channel`` value from the completed ADC scan ``channel_counts``.
def get_scanned_channel_raw(
    channel_counts: dict[int, int],
    channel: int,
) -> int:
    """Return one raw channel value from a completed ADC scan.

    Args:
        channel_counts (dict[int, int]): Mapping of ADC channel numbers to raw counts.
        channel (int): Active station sensor channel to retrieve.

    Returns:
        Raw ADC counts stored for ``channel``.

    Raises:
        ValueError: If ``channel`` is not an active sensor channel.
        KeyError: If the completed scan does not contain ``channel``.
    """
    valid_channels = {
        CH_HOT,
        CH_COLD,
        CH_FLOW,
        CH_AMBIENT,
    }

    if channel not in valid_channels:
        raise ValueError(f"Unsupported sensor channel: {channel}")

    return channel_counts[channel]

# endregion Scanned-Channel Lookup

# region Sensor Reader

# Reads ADC channels with ``SensorReader`` and converts their values into sensor measurements.
class SensorReader:
    """Read and convert active station sensors through a borrowed ADC.

    Args:
        adc (SensorAdc): ADC-compatible object supplied by the station assembly
            layer. The caller retains ownership of the object.
        calibration_path (Path | None): Optional JSON calibration path. When
            omitted, nominal sensor-conversion values are used. An explicitly
            supplied path must exist.

    Resource ownership:
        The caller constructs, configures, owns, and closes the supplied ADC.
    """
    # region Initialization

    # Stores the borrowed ADC ``_adc``, loads conversion configuration, and caches spans.
    def __init__(
        self,
        adc: SensorAdc,
        *,
        calibration_path: Path | None = None,
    ) -> None:
        self._adc = adc

        self._conversion_config = load_sensor_conversion_config(calibration_path)
        self._temperature_span = self._conversion_config.temperature_span
        self._temperature_span_f = self._conversion_config.temperature_span_f
        self._flow_span = self._conversion_config.flow_span

    # endregion Initialization

    # region ADC Access

    # Reads raw ADC counts from ``self._adc`` for the specified ADC ``channel``.
    def get_adc_raw(self, channel: int) -> int:
        """Read one raw ADC channel.

        Args:
            channel (int): ADC analog input channel number.

        Returns:
            Raw ADC result in counts.

        Raises:
            RuntimeError: If ``self._adc`` returns no reading.
        """
        raw_counts = self._adc.read_single(channel)
        if raw_counts is None:
            raise RuntimeError(f"ADC returned no value for channel {channel}")

        return raw_counts

    # Reads raw counts from ADC ``channel`` and converts them using ``self._conversion_config``.
    def get_adc_voltage(self, channel: int) -> float:
        """Read one ADC channel and convert it to volts.

        Args:
            channel (int): ADC analog input channel number.

        Returns:
            ADC input voltage in volts.
        """
        channel_raw_counts = self.get_adc_raw(channel)
        return adc_counts_to_voltage(
            channel_raw_counts,
            self._conversion_config,
        )

    # endregion ADC Access

    # region Sensor Measurements

    # Reads hot-water voltage ``hot_voltage_v`` and converts it with ``_temperature_span``.
    def get_hot_temp_c(self) -> float:
        """Read the hot-water 4-20 mA transmitter.

        Returns:
            Hot-water temperature in degrees Celsius.

        Calibration:
            Uses the effective temperature span and electrical configuration.
        """
        hot_voltage_v = self.get_adc_voltage(CH_HOT)
        return voltage_to_linear_loop_value(
            hot_voltage_v,
            self._temperature_span,
            self._conversion_config,
        )

    # Reads cold-water voltage ``cold_voltage_v`` and converts it with ``_temperature_span``.
    def get_cold_temp_c(self) -> float:
        """Read the cold-water 4-20 mA transmitter.

        Returns:
            Cold-water temperature in degrees Celsius.

        Calibration:
            Uses the effective temperature span and electrical configuration.
        """
        cold_voltage_v = self.get_adc_voltage(CH_COLD)
        return voltage_to_linear_loop_value(
            cold_voltage_v,
            self._temperature_span,
            self._conversion_config,
        )

    # Reads flow voltage ``flow_voltage_v`` and converts it with ``_flow_span``.
    def get_flow_gpm(self) -> float:
        """Read the 4-20 mA flow transmitter.

        Returns:
            Flow rate in gallons per minute.

        Calibration:
            Uses the effective flow span and electrical configuration.
        """
        flow_voltage_v = self.get_adc_voltage(CH_FLOW)
        return voltage_to_linear_loop_value(
            flow_voltage_v,
            self._flow_span,
            self._conversion_config,
        )

    # Converts LM35 voltage ``ambient_voltage_v`` into degrees Celsius.
    def get_ambient_temp_c(self) -> float:
        """Read the PCB-mounted LM35 ambient sensor.

        Returns:
            Ambient temperature in degrees Celsius.
        """
        ambient_voltage_v = self.get_adc_voltage(CH_AMBIENT)
        return lm35_voltage_to_temp_c(ambient_voltage_v)

    # endregion Sensor Measurements

    # region Grouped Sensor Snapshots

    # Reads all active channels into ``channel_counts`` and returns one ``SensorSnapshot``.
    def get_sensor_snapshot(self) -> SensorSnapshot:
        """Read all active sensors into one structured snapshot.

        Returns:
            ``SensorSnapshot`` containing raw counts and converted temperature
            and flow measurements.

        Timing:
            ADC channels are read sequentially during one scan.
            Measurements are tightly grouped but not physically simultaneous.
        """
        channel_counts = self._adc.read_range(CH_HOT, CH_AMBIENT)

        hot_raw_counts = get_scanned_channel_raw(channel_counts, CH_HOT)
        cold_raw_counts = get_scanned_channel_raw(channel_counts, CH_COLD)
        flow_raw_counts = get_scanned_channel_raw(channel_counts, CH_FLOW)
        ambient_raw_counts = get_scanned_channel_raw(channel_counts, CH_AMBIENT)

        hot_voltage_v = adc_counts_to_voltage(
            hot_raw_counts,
            self._conversion_config,
        )
        cold_voltage_v = adc_counts_to_voltage(
            cold_raw_counts,
            self._conversion_config,
        )
        flow_voltage_v = adc_counts_to_voltage(
            flow_raw_counts,
            self._conversion_config,
        )
        ambient_voltage_v = adc_counts_to_voltage(
            ambient_raw_counts,
            self._conversion_config,
        )

        return SensorSnapshot(
            hot_raw_counts=hot_raw_counts,
            cold_raw_counts=cold_raw_counts,
            flow_raw_counts=flow_raw_counts,
            ambient_raw_counts=ambient_raw_counts,
            hot_temp_c=voltage_to_linear_loop_value(
                hot_voltage_v,
                self._temperature_span,
                self._conversion_config,
            ),
            hot_temp_f=voltage_to_linear_loop_value(
                hot_voltage_v,
                self._temperature_span_f,
                self._conversion_config,
            ),
            cold_temp_c=voltage_to_linear_loop_value(
                cold_voltage_v,
                self._temperature_span,
                self._conversion_config,
            ),
            cold_temp_f=voltage_to_linear_loop_value(
                cold_voltage_v,
                self._temperature_span_f,
                self._conversion_config,
            ),
            ambient_temp_c=lm35_voltage_to_temp_c(ambient_voltage_v),
            ambient_temp_f=lm35_voltage_to_temp_f(ambient_voltage_v),
            flow_gpm=voltage_to_linear_loop_value(
                flow_voltage_v,
                self._flow_span,
                self._conversion_config,
            ),
        )

    # endregion Grouped Sensor Snapshots

# endregion Sensor Reader
