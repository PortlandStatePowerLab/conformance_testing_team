from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence, Union, List, Dict
from smbus2 import SMBus, i2c_msg
import time


class InputMode(Enum):
    SingleEnded = 1   # SGL/DIF = 1
    Differential = 0  # SGL/DIF = 0


class ClockType(Enum):
    External = 1  # CLK = 1
    Internal = 0  # CLK = 0


class Polarity(Enum):
    Unipolar = 0   # BIP/UNI = 0
    Bipolar = 1    # BIP/UNI = 1


class ResetMode(Enum):
    Reset = 0      # RST = 0
    NoAction = 1   # RST = 1


class ScanMode(Enum):
    # SCAN[1:0] (Table 5)
    ScanAIN0ToCS   = 0b00
    RepeatSelect8x = 0b01
    ScanAIN6ToCS   = 0b10
    ConvertSelected = 0b11


class ReferenceVoltage(Enum):
    # SEL[2:0] (Table 6)
    VDD_AnalogIn                  = 0b000
    ExternalRef                   = 0b010
    InternalRef_AlwaysOFF_AnalogIn = 0b100
    InternalRef_AlwaysON_AnalogIn  = 0b101
    InternalRef_AlwaysOFF_RefOut    = 0b110
    InternalRef_AlwaysON_RefOut     = 0b111


class Max1238:
    """
    Minimal MAX1238 12-bit I2C ADC driver.

    - Setup byte (REG=1): [REG SEL2 SEL1 SEL0 CLK BIP/UNI RST X]
    - Config byte (REG=0): [REG SCAN1 SCAN0 CS3 CS2 CS1 CS0 SGL/DIF]

    Reading returns 12-bit results as ((MSB&0x0F)<<8)|LSB
    """
    def __init__(self, address: int = 0x35, bus_num: int = 1) -> None:
        self.address = address
        self.bus = SMBus(bus_num)

    # ---------- Low-level I2C helper ----------
    def _xfer(
        self,
        write_bytes: Optional[Union[int, Sequence[int]]] = None,
        read_len: int = 0,
        retries: int = 1,
        retry_delay_s: float = 0.002,
    ) -> List[int]:
        """
        One atomic I2C transaction: optional write -> repeated START -> optional read.
        Returns list[int] of length read_len (or []).
        """
        # Normalize write payload
        if write_bytes is None:
            to_write: Optional[List[int]] = None
        elif isinstance(write_bytes, int):
            if not (0 <= write_bytes <= 255):
                raise ValueError("write byte out of range (0..255)")
            to_write = [write_bytes]
        else:
            to_write = list(write_bytes)
            if any((b < 0 or b > 255) for b in to_write):
                raise ValueError("one or more write bytes out of range (0..255)")

        if read_len < 0:
            raise ValueError("read_len must be >= 0")

        attempt = 0
        last_err: Optional[BaseException] = None
        while attempt <= retries:
            try:
                msgs = []
                if to_write is not None:
                    msgs.append(i2c_msg.write(self.address, to_write))
                if read_len:
                    msgs.append(i2c_msg.read(self.address, read_len))
                if not msgs:
                    return []

                self.bus.i2c_rdwr(*msgs)
                return list(msgs[-1]) if read_len else []
            except OSError as e:
                last_err = e
                if attempt == retries:
                    raise
                time.sleep(retry_delay_s)
                attempt += 1

        # Should not get here
        if last_err:
            raise last_err
        return []

    # ---------- Byte builders ----------
    def _build_setup_byte(
        self,
        referenceVoltage: ReferenceVoltage,
        clock: ClockType,
        polarity: Polarity,
        reset: ResetMode,
    ) -> int:
        # REG=1, then SEL[2:0], CLK, BIP/UNI, RST, X
        return (
            (1 << 7)
            | (referenceVoltage.value << 4)
            | (clock.value << 3)
            | (polarity.value << 2)
            | (reset.value << 1)
            | 0
        )

    def _build_config_byte(
        self,
        scan: ScanMode,
        channel: int,
        mode: InputMode,
    ) -> int:
        if not (0 <= channel <= 11):
            raise ValueError("channel must be 0..11 for MAX1238")
        # REG=0, SCAN[1:0], CS[3:0], SGL/DIF
        return (
            (0 << 7)
            | (scan.value << 5)
            | ((channel & 0x0F) << 1)
            | (mode.value & 0x01)
        )

    # ---------- High-level ops ----------
    def setup_adc(
        self,
        referenceVoltage: ReferenceVoltage = ReferenceVoltage.InternalRef_AlwaysON_AnalogIn,
        clock: ClockType = ClockType.Internal,
        polarity: Polarity = Polarity.Unipolar,
        reset: ResetMode = ResetMode.NoAction,
    ) -> None:
        setup_byte = self._build_setup_byte(referenceVoltage, clock, polarity, reset)
        self._xfer(setup_byte, 0)

    def read_single(
        self,
        channel: int,
        mode: InputMode = InputMode.SingleEnded,
    ) -> Optional[int]:
        cfg = self._build_config_byte(ScanMode.ConvertSelected, channel, mode)
        msb, lsb = self._xfer(cfg, 2)
        return ((msb & 0x0F) << 8) | lsb

    def read_range(
        self,
        start_channel: int,
        end_channel: int,
        mode: InputMode = InputMode.SingleEnded,
    ) -> Dict[int, int]:
        if not (0 <= start_channel <= end_channel <= 11):
            raise ValueError("Invalid channel range")

        if start_channel >= 6:
            scan = ScanMode.ScanAIN6ToCS
            base = 6
        else:
            scan = ScanMode.ScanAIN0ToCS
            base = 0

        cfg = self._build_config_byte(scan, end_channel, mode)
        n_res = (end_channel - base + 1)
        raw = self._xfer(cfg, 2 * n_res)

        words = [((raw[i] & 0x0F) << 8) | raw[i + 1] for i in range(0, len(raw), 2)]
        channels = list(range(base, end_channel + 1))
        results = dict(zip(channels, words))
        return {ch: results[ch] for ch in range(start_channel, end_channel + 1)}

    def read_multiple(
        self,
        start_channel: int,
        count: int,
        mode: InputMode = InputMode.SingleEnded,
    ) -> List[int]:
        if not (0 <= start_channel <= 11) or not (1 <= count <= 12 - start_channel):
            raise ValueError("Invalid channel/count")

        end_ch = start_channel + count - 1
        if start_channel >= 6:
            scan, base = ScanMode.ScanAIN6ToCS, 6
        else:
            scan, base = ScanMode.ScanAIN0ToCS, 0

        cfg = self._build_config_byte(scan, end_ch, mode)
        n_results = (end_ch - base + 1)
        raw = self._xfer(cfg, 2 * n_results)

        words = [((raw[i] & 0x0F) << 8) | raw[i + 1] for i in range(0, len(raw), 2)]
        drop = start_channel - base
        return words[drop : drop + count]

    # Optional: context management / cleanup
    def close(self) -> None:
        try:
            self.bus.close()
        except Exception:
            pass

    def __enter__(self) -> "Max1238":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
