"""Direct Raspberry Pi GPIO driver for the WH1 valve relay."""

from __future__ import annotations

from types import ModuleType


class GpioValveDriver:
    """Drive one valve-relay GPIO and safely manage its lifecycle"""

    def __init__(self, gpio: ModuleType, pin: int) -> None:
        """Store the GPIO module and BCM pin used by the valve relay

        Args:
            gpio: Imported GPIO-compatible module
            pin: BCM GPIO pin number controlling the valve relay

        Safety:
            The builder must intialize the output LOW before constructing this driver
        """
        self._gpio = gpio
        self._pin = pin
        self._commands_disabled = False
        self._cleanup_complete = False

    def _require_active(self)->None:
        """Reject valve commands after resource cleanup has begun"""
        if self._commands_disabled:
            raise RuntimeError("valve GPIO driver cleanup has already begun")

    def open(self) -> None:
        """Assert the relay output HIGH to command the valve open"""
        self._require_active()
        self._gpio.output(self._pin, self._gpio.HIGH)

    def close(self) -> None:
        """Return the relay output LOW to command the valve closed"""
        self._require_active()
        self._gpio.output(self._pin, self._gpio.LOW)

    def cleanup(self) -> None:
        """Force the valve command LOW and release the GPIO pin once

        Safety:
            The first call permanently disables normal valve commands. GPIO release
            may be retried after failure, and repeated successful calls do nothing.
            """
        if self._cleanup_complete:
            return

        close_error: BaseException | None = None
        if not self._commands_disabled:
            self._commands_disabled = True
            try:
                self._gpio.output(self._pin, self._gpio.LOW)
            except BaseException as error:
                close_error = error

        try:
            self._gpio.cleanup(self._pin)
        except BaseException as cleanup_error:
            if close_error is None:
                raise
            close_error.add_note(
                f"GPIO pin cleanup also failed: {cleanup_error!r}"
            )
            raise close_error from cleanup_error

        self._cleanup_complete = True
        if close_error is not None:
            raise close_error

    def __enter__(self) -> "GpioValveDriver":
        """Return this active driver for context-manager use"""
        self._require_active()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Force LOW and release the GPIO pin when leaving the context"""
        self.cleanup()
