"""MAX1238 I2C ADC driver adapted from Blake's staged hardware repository."""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional, Sequence


class InputMode(Enum):
    SINGLE_ENDED = 1
    DIFFERENTIAL = 0


class ClockType(Enum):
    EXTERNAL = 1
    INTERNAL = 0


class Polarity(Enum):
    UNIPOLAR = 0
    BIPOLAR = 1


class ResetMode(Enum):
    RESET = 0
    NO_ACTION = 1


class ScanMode(Enum):
    SCAN_AIN0_TO_CS = 0b00
    REPEAT_SELECT_8X = 0b01
    SCAN_AIN6_TO_CS = 0b10
    CONVERT_SELECTED = 0b11


class ReferenceVoltage(Enum):
    VDD_ANALOG_IN = 0b000
    EXTERNAL_REF = 0b010
    INTERNAL_REF_ALWAYS_OFF_ANALOG_IN = 0b100
    INTERNAL_REF_ALWAYS_ON_ANALOG_IN = 0b101
    INTERNAL_REF_ALWAYS_OFF_REF_OUT = 0b110
    INTERNAL_REF_ALWAYS_ON_REF_OUT = 0b111


class Max1238Adc:
    """Minimal 12-bit MAX1238 driver with explicit resource ownership."""

    def __init__(self, *, address: int = 0x35, bus_number: int = 1) -> None:
        # Linux-only import remains out of Windows validation paths.
        from smbus2 import SMBus, i2c_msg

        self.address = address
        self._i2c_msg = i2c_msg
        self._bus = SMBus(bus_number)

    def _transfer(
        self,
        write_bytes: int | Sequence[int] | None = None,
        read_length: int = 0,
        *,
        retries: int = 1,
        retry_delay_seconds: float = 0.002,
    ) -> list[int]:
        if write_bytes is None:
            payload = None
        elif isinstance(write_bytes, int):
            payload = [write_bytes]
        else:
            payload = list(write_bytes)
        if payload is not None and any(not 0 <= byte <= 255 for byte in payload):
            raise ValueError("MAX1238 write bytes must be between 0 and 255")
        if read_length < 0:
            raise ValueError("read_length must not be negative")

        for attempt in range(retries + 1):
            try:
                messages = []
                if payload is not None:
                    messages.append(self._i2c_msg.write(self.address, payload))
                if read_length:
                    messages.append(self._i2c_msg.read(self.address, read_length))
                if not messages:
                    return []
                self._bus.i2c_rdwr(*messages)
                return list(messages[-1]) if read_length else []
            except OSError:
                if attempt == retries:
                    raise
                time.sleep(retry_delay_seconds)
        return []

    @staticmethod
    def _setup_byte(
        reference: ReferenceVoltage,
        clock: ClockType,
        polarity: Polarity,
        reset: ResetMode,
    ) -> int:
        return (
            (1 << 7)
            | (reference.value << 4)
            | (clock.value << 3)
            | (polarity.value << 2)
            | (reset.value << 1)
        )

    @staticmethod
    def _configuration_byte(scan: ScanMode, channel: int, mode: InputMode) -> int:
        if not 0 <= channel <= 11:
            raise ValueError("MAX1238 channel must be between 0 and 11")
        return (scan.value << 5) | ((channel & 0x0F) << 1) | mode.value

    def setup(self) -> None:
        setup_byte = self._setup_byte(
            ReferenceVoltage.INTERNAL_REF_ALWAYS_ON_ANALOG_IN,
            ClockType.EXTERNAL,
            Polarity.UNIPOLAR,
            ResetMode.NO_ACTION,
        )
        self._transfer(setup_byte)
        time.sleep(0.010)

    def read_single(
        self, channel: int, mode: InputMode = InputMode.SINGLE_ENDED
    ) -> Optional[int]:
        configuration = self._configuration_byte(
            ScanMode.CONVERT_SELECTED, channel, mode
        )
        most_significant, least_significant = self._transfer(configuration, 2)
        return ((most_significant & 0x0F) << 8) | least_significant

    def read_range(
        self,
        start_channel: int,
        end_channel: int,
        mode: InputMode = InputMode.SINGLE_ENDED,
    ) -> dict[int, int]:
        if not 0 <= start_channel <= end_channel <= 11:
            raise ValueError("invalid MAX1238 channel range")
        if start_channel >= 6:
            scan = ScanMode.SCAN_AIN6_TO_CS
            base_channel = 6
        else:
            scan = ScanMode.SCAN_AIN0_TO_CS
            base_channel = 0
        configuration = self._configuration_byte(scan, end_channel, mode)
        result_count = end_channel - base_channel + 1
        raw_bytes = self._transfer(configuration, 2 * result_count)
        words = [
            ((raw_bytes[index] & 0x0F) << 8) | raw_bytes[index + 1]
            for index in range(0, len(raw_bytes), 2)
        ]
        results = dict(zip(range(base_channel, end_channel + 1), words))
        return {
            channel: results[channel]
            for channel in range(start_channel, end_channel + 1)
        }

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
