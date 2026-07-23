"""Construct and safely configure the WH1 GPIO valve driver."""

from software.station.station_hardware_map import VALVE_PIN
from software.valve.gpio_valve_driver import GpioValveDriver


def build_gpio_valve(*, pin: int = VALVE_PIN) -> GpioValveDriver:
    """Build a valve driver with its output initialized LOW."""
    import RPi.GPIO as GPIO

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    return GpioValveDriver(GPIO, pin)
