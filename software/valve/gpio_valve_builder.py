"""Construct and safely configure the WH station GPIO valve driver."""

try:
    from ..station.station_hardware_map import VALVE_PIN
except ImportError:
    from station.station_hardware_map import VALVE_PIN

from .gpio_valve_driver import GpioValveDriver

# Constructs the GPIO valve driver
def build_gpio_valve(*, pin: int = VALVE_PIN) -> GpioValveDriver:
    """Build a valve driver with its output initialized LOW.

    Args:
        pin (int): BCM GPIO pin connected to the valve relay.

    Returns:
        A configured ``GpioValveDriver`` ready for valve commands.

    Ownership:
        The caller owns the returned driver and must call ``cleanup()`` when
        valve control is no longer needed.

    Safety:
        Initializes the relay output LOW so construction of the driver doesnt open the
        valve unintentionally.
    """

    # Imported Lazily because RPi.GPIO is available only on the Raspberry Pi.
    import RPi.GPIO as GPIO # pyright: ignore[reportMissingModuleSource]

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    return GpioValveDriver(GPIO, pin)
