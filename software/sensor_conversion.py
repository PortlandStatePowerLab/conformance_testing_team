"""Pure sensor-conversion configuration and mathematical operations.

This module defines the station's nominal electrical and sensor-range values,
plus the immutable ``SensorConversionConfig`` used by conversion functions.
Effective ADC limits and current-loop spans are derived from that configuration
so nominal and calibrated operation share one source of truth.

The functions transform ADC counts into voltage, shunt voltage into loop
current, linear current-loop signals into engineering values, and LM35 voltage
into ambient temperature. This module performs no hardware access, lifecycle,
file, timing, or output operations.
"""

# region Imports

# Enables postponed evaluation so annotations can reference classes defined later.
from __future__ import annotations

# Dataclass decorator from the Python standard library.
from dataclasses import dataclass

# endregion Imports

# region Conversion Constants

# Nominal MAX1238 and installed signal-path values.
#
# These constants remain unchanged when a caller supplies calibrated values in
# a separate ``SensorConversionConfig``.

# ADC (MAX1238) datasheet specifies 1 LSB = VREF / 2^N
ADC_RESOLUTION_BITS = 12  # 2^12 = 4096 conversion steps (resolution)
ADC_CODE_COUNT = 1 << ADC_RESOLUTION_BITS  # 4096 conversion steps (conversion divisor)
ADC_MAX_CODE = ADC_CODE_COUNT - 1  # Highest returned code: 4095

NOMINAL_ADC_REFERENCE_V = 4.096
NOMINAL_SHUNT_OHMS = 120.0

NOMINAL_CURRENT_LOOP_MIN_MA = 4.0
NOMINAL_CURRENT_LOOP_MAX_MA = 20.0

NOMINAL_TEMPERATURE_MIN_C = -50.0
NOMINAL_TEMPERATURE_MAX_C = 150.0

NOMINAL_FLOW_MIN_GPM = 0.0
NOMINAL_FLOW_MAX_GPM = 10.0

# endregion Conversion Constants

# region Sensor Conversion Configuration

# Packages either nominal or calibrated values in ``SensorConversionConfig``.
@dataclass(frozen=True)
class SensorConversionConfig:
    """Store electrical and sensor-range values used by conversions.

    Defaults describe the nominal station signal path. Callers may override
    individual fields while omitted fields retain their nominal values.
    """

    adc_reference_voltage_v: float = NOMINAL_ADC_REFERENCE_V
    adc_code_count: int = ADC_CODE_COUNT

    shunt_ohms: float = NOMINAL_SHUNT_OHMS
    current_loop_min_ma: float = NOMINAL_CURRENT_LOOP_MIN_MA
    current_loop_max_ma: float = NOMINAL_CURRENT_LOOP_MAX_MA

    temperature_min_c: float = NOMINAL_TEMPERATURE_MIN_C
    temperature_max_c: float = NOMINAL_TEMPERATURE_MAX_C

    flow_min_gpm: float = NOMINAL_FLOW_MIN_GPM
    flow_max_gpm: float = NOMINAL_FLOW_MAX_GPM

    # Validates all configuration values in ``SensorConversionConfig`` fields after dataclass initialization.
    def __post_init__(self) -> None:
        """Validate active sensor-conversion values.

        Raises:
            ValueError: If an electrical range, sensor range, or ADC
                configuration is invalid.
        """
        if self.adc_reference_voltage_v <= 0.0:
            raise ValueError("adc_reference_voltage_v must be greater than zero")

        if self.adc_code_count <= 0:
            raise ValueError("adc_code_count must be greater than zero")

        if self.shunt_ohms <= 0.0:
            raise ValueError("shunt_ohms must be greater than zero")

        if self.current_loop_max_ma <= self.current_loop_min_ma:
            raise ValueError("current_loop_max_ma must exceed current_loop_min_ma")

        if self.temperature_max_c <= self.temperature_min_c:
            raise ValueError("temperature_max_c must exceed temperature_min_c")

        if self.flow_max_gpm <= self.flow_min_gpm:
            raise ValueError("flow_max_gpm must exceed flow_min_gpm")

    # Derives the highest valid ADC output ``adc_max_code`` from the configured code count ``adc_code_count``.
    @property
    def adc_max_code(self) -> int:
        """Return the highest valid ADC output code."""
        return self.adc_code_count - 1

    # Builds ``temperature_span`` from the effective temperature limits.
    @property
    def temperature_span(self) -> "LinearCurrentLoopSpan":
        """Return the effective temperature span."""
        return LinearCurrentLoopSpan(
            engineering_min_value=self.temperature_min_c,
            engineering_max_value=self.temperature_max_c,
            units="degC",
        )

    # Builds ``temperature_span_f`` from the effective temperature limits.
    @property
    def temperature_span_f(self) -> "LinearCurrentLoopSpan":
        """Return the effective temperature span in degrees Fahrenheit."""
        return LinearCurrentLoopSpan(
            engineering_min_value=temp_c_to_temp_f(self.temperature_min_c),
            engineering_max_value=temp_c_to_temp_f(self.temperature_max_c),
            units="degF",
        )

    # Builds ``flow_span`` from the effective flow limits.
    @property
    def flow_span(self) -> "LinearCurrentLoopSpan":
        """Return the effective flow span."""
        return LinearCurrentLoopSpan(
            engineering_min_value=self.flow_min_gpm,
            engineering_max_value=self.flow_max_gpm,
            units="gpm",
        )


NOMINAL_SENSOR_CONFIG = SensorConversionConfig()

# endregion Sensor Conversion Configuration

# region Current-Loop Span Model

# Stores the engineering-unit range for a linear current-loop sensor.
@dataclass(frozen=True)
class LinearCurrentLoopSpan:
    """Store the engineering-unit range of a linear current-loop sensor.

    Attributes:
        engineering_min_value: Engineering value represented by minimum current.
        engineering_max_value: Engineering value represented by maximum current.
        units: Engineering-unit label such as ``degC`` or ``gpm``.
    """

    engineering_min_value: float
    engineering_max_value: float
    units: str

# endregion Current-Loop Span Model

# region Conversion Functions

# Converts the raw ADC count ``raw_counts`` into ADC input voltage.
def adc_counts_to_voltage(
    raw_counts: int,
    conversion_config: SensorConversionConfig = NOMINAL_SENSOR_CONFIG,
) -> float:
    """Convert raw ADC counts to input voltage.

    Args:
        raw_counts (int): Raw ADC result in counts.
        conversion_config (SensorConversionConfig): Active conversion values.

    Returns:
        Input voltage corresponding to ``raw_counts``.

    Raises:
        ValueError: If the configured ADC code count or reference voltage is not
        positive, or if ``raw_counts`` is outside the configured valid range.

    Assumptions:
        The ADC uses ``reference voltage / code count`` volts per conversion step.
    """
    if not 0 <= raw_counts <= conversion_config.adc_max_code:
        raise ValueError(
            "raw_counts must be between "
            f"0 and {conversion_config.adc_max_code}, got {raw_counts}"
        )

    if conversion_config.adc_code_count <= 0:
        raise ValueError("adc_code_count must be greater than zero")

    if conversion_config.adc_reference_voltage_v <= 0:
        raise ValueError("adc_reference_voltage_v must be greater than zero")

    return (
        float(raw_counts)
        / float(conversion_config.adc_code_count)
        * conversion_config.adc_reference_voltage_v
    )

# Converts a shunt-voltage measurement ``measured_voltage_v`` into milliamps.
def voltage_to_loop_current_ma(
    measured_voltage_v: float,
    conversion_config: SensorConversionConfig = NOMINAL_SENSOR_CONFIG,
) -> float:
    """Convert measured shunt voltage to transmitter loop current.

    Args:
        measured_voltage_v (float): Measured voltage across the current-loop shunt in volts.
        conversion_config (SensorConversionConfig): Active ``SensorConversionConfig`` values.

    Returns:
        Loop current in milliamps corresponding to the measured voltage.
        Negative calculated current is limited to zero.

    Raises:
        ValueError: If ``conversion_config.shunt_ohms`` is not positive.

    Assumptions:
        The conversion assumes a linear relationship between voltage and current
        according to Ohm's law (I = V / R).
    """
    if conversion_config.shunt_ohms <= 0:
        raise ValueError("shunt_ohms must be greater than zero")

    current_a = max(
        measured_voltage_v / conversion_config.shunt_ohms,
        0.0,
    )  # Limit negative current to zero
    return current_a * 1000.0  # Convert to milliamps

# Converts current-loop shunt voltage ``measured_voltage_v`` into a sensor's measured quantity described by ``loop_span``.
def voltage_to_linear_loop_value(
    measured_voltage_v: float,
    loop_span: LinearCurrentLoopSpan,
    conversion_config: SensorConversionConfig = NOMINAL_SENSOR_CONFIG,
) -> float:
    """Convert current-loop voltage into a linear engineering value.

    Args:
        measured_voltage_v: Voltage measured across the current-loop shunt.
        loop_span: Effective ``LinearCurrentLoopSpan`` engineering-unit range.
        conversion_config: Active electrical and calibration values.

    Returns:
        Converted value in ``loop_span.units``.
    """
    current_ma = voltage_to_loop_current_ma(
        measured_voltage_v,
        conversion_config,
    )

    # Calculates the configured 4-20 mA width ``current_span_ma``.
    current_span_ma = (
        conversion_config.current_loop_max_ma
        - conversion_config.current_loop_min_ma
    )

    # Locates ``current_ma`` proportionally within ``current_span_ma``.
    normalized_position = (
        current_ma - conversion_config.current_loop_min_ma
    ) / current_span_ma

    # Calculates the sensor output width ``engineering_span``.
    engineering_span = (
        loop_span.engineering_max_value
        - loop_span.engineering_min_value
    )

    return (
        loop_span.engineering_min_value
        + normalized_position * engineering_span
    )

# Converts LM35 voltage ``volts_v`` into temperature in degrees Celsius.
def lm35_voltage_to_temp_c(volts_v: float) -> float:
    """Convert LM35 sensor output voltage to ambient temperature in degrees Celsius.

    Args:
        volts_v (float): Measured LM35 output voltage in volts.

    Returns:
        Temperature in degrees Celsius corresponding to the measured voltage.

    Assumptions:
        The LM35 sensor has a linear response of 10 mV/deg C with an offset of
        0 deg C at 0 V.
    """
    return volts_v * 100.0  # Convert volts to deg C (10 mV/deg C)

# Converts LM35 voltage ``volts_v`` into temperature in degrees Fahrenheit.
def lm35_voltage_to_temp_f(volts_v: float) -> float:
    """Convert LM35 sensor output voltage to ambient temperature in degrees Fahrenheit.

    Args:
        volts_v (float): Measured LM35 output voltage in volts.

    Returns:
        Temperature in degrees Fahrenheit corresponding to the measured voltage.

    Assumptions:
        The LM35 sensor has a linear response of 10 mV/deg C with an offset of
        0 deg C at 0 V, reported here directly in degrees Fahrenheit.
    """
    return volts_v * 180.0 + 32.0

# Converts temperature ``temp_c`` from degrees Celsius to degrees Fahrenheit.
def temp_c_to_temp_f(temp_c: float) -> float:
    """Convert temperature from degrees Celsius to degrees Fahrenheit.

    Args:
        temp_c (float): Temperature in degrees Celsius.

    Returns:
        Temperature in degrees Fahrenheit.
    """
    return temp_c * 9.0 / 5.0 + 32.0

# endregion Conversion Functions
