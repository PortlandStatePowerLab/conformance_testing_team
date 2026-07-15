from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from smbus2 import SMBus

# -----------------------------
# Helpers
# -----------------------------
from helpers.helper_power_functions import (
    #get_integer_from_u16,
    #get_integer_from_s16,
    #get_32_bit_little_endian,
    get_power_data,
    #get_power_factor_from_11bit_register,
    get_calibration_from_JSON,
    set_calibration,
    read_measurement_values,
    calibrate,
    get_pi_number,
)

from helpers.hardware_map import (
        I2C_BUS,
        ACS37800_I2C_ADDR,
)

OUTPUT_FOLDER = Path("power_diagnostics")

EEPROM_REGISTERS = {
    0x0B: "EEPROM_CURRENT_TRIM_AVERAGING",
    0x0C: "EEPROM_VOLTAGE_OFFSET_AVERAGING",
    0x0D: "EEPROM_PHASE_DELAY_OVERCURRENT",
    0x0E: "EEPROM_VOLTAGE_EVENTS_ZERO_CROSSING",
    0x0F: "EEPROM_RMS_WINDOW_DIO_I2C",
}

SHADOW_REGISTERS = {
    0x1B: "SHADOW_CURRENT_TRIM_AVERAGING",
    0x1C: "SHADOW_VOLTAGE_OFFSET_AVERAGING",
    0x1D: "SHADOW_PHASE_DELAY_OVERCURRENT",
    0x1E: "SHADOW_VOLTAGE_EVENTS_ZERO_CROSSING",
    0x1F: "SHADOW_RMS_WINDOW_DIO_I2C",
}

LIVE_REGISTERS = {
    0x20: "VRMS_IRMS",
    0x21: "PACTIVE_PIMAG",
    0x22: "PAPPARENT_PFACTOR_FLAGS",
    0x25: "NUMPTSOUT",
    0x26: "RMS_AVERAGE_STAGE_1",
    0x27: "RMS_AVERAGE_STAGE_2",
    0x28: "PACTIVE_AVERAGE_STAGE_1",
    0x29: "PACTIVE_AVERAGE_STAGE_2",
    0x2A: "VCODES_ICODES",
    0x2C: "PINSTANT",
    0x2D: "STATUS_FLAGS",
}


def get_integer_from_u16(x: int) -> int:
    """Return the lower 16 bits as an unsigned integer."""
    return x & 0xFFFF


def get_integer_from_s16(x: int) -> int:
    """Convert the lower 16 bits to signed two's-complement."""
    x &= 0xFFFF
    return x - 0x10000 if (x & 0x8000) else x


def sign_extend(value: int, width: int) -> int:
    """Interpret value as a signed two's-complement integer of width bits."""
    mask = (1 << width) - 1
    value &= mask
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def extract_bits(value: int, msb: int, lsb: int) -> int:
    """Extract an inclusive bit range, for example bits 18:9."""
    width = msb - lsb + 1
    return (value >> lsb) & ((1 << width) - 1)


def get_power_factor_from_11bit_register(raw_bits: int) -> float:
    """Decode PFACTOR as signed 11-bit fixed point with 10 fractional bits."""
    return sign_extend(raw_bits, 11) / (2**10)


def get_32_bit_little_endian(
    bus: SMBus,
    register: int,
    retries: int = 3,
    retry_delay_s: float = 0.05,
) -> int:
    """Read one 32-bit little-endian ACS37800 register."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            b = bus.read_i2c_block_data(ACS37800_I2C_ADDR, register, 4)
            if len(b) != 4:
                raise OSError(
                    f"Register 0x{register:02X}: expected 4 bytes, received {len(b)}"
                )
            return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
        except OSError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay_s)
    raise OSError(
        f"Unable to read ACS37800 register 0x{register:02X} after {retries} attempts"
    ) from last_error


def raw_record(address: int, name: str, value: int) -> dict[str, Any]:
    return {
        "address": f"0x{address:02X}",
        "name": name,
        "raw_hex": f"0x{value:08X}",
        "raw_unsigned": value,
        "bytes_little_endian": [
            value & 0xFF,
            (value >> 8) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 24) & 0xFF,
        ],
    }


CRS_SNS_GAIN = {0: 1.0, 1: 2.0, 2: 3.0, 3: 3.5, 4: 4.0, 5: 4.5, 6: 5.5, 7: 8.0}
FAULT_DELAY_US = {0: 0.0, 1: 0.0, 2: 4.75, 3: 9.25, 4: 13.75, 5: 18.5, 6: 23.25, 7: 27.75}
ECC_MEANING = {0: "No error", 1: "Error detected and corrected", 2: "Uncorrectable error", 3: "No defined meaning"}


def add_ecc(result: dict[str, Any], value: int) -> None:
    ecc = extract_bits(value, 27, 26)
    result["ECC"] = {"bits": "27:26", "value": ecc, "meaning": ECC_MEANING[ecc]}
    result["EEPROM_BITS_31_28"] = {"bits": "31:28", "value": extract_bits(value, 31, 28), "meaning": "Datasheet: no meaning"}


def decode_register_0b_1b(value: int, *, eeprom: bool) -> dict[str, Any]:
    qvo_raw = extract_bits(value, 8, 0)
    sns_raw = extract_bits(value, 18, 9)
    crs_sns = extract_bits(value, 21, 19)
    result = {
        "QVO_FINE": {"bits": "8:0", "raw": qvo_raw, "signed": sign_extend(qvo_raw, 9), "description": "Current-channel fine offset trim"},
        "SNS_FINE": {"bits": "18:9", "raw": sns_raw, "signed": sign_extend(sns_raw, 10), "description": "Current-channel fine gain trim"},
        "CRS_SNS": {"bits": "21:19", "raw": crs_sns, "gain_multiplier": CRS_SNS_GAIN[crs_sns], "description": "Current-channel coarse analog gain selection"},
        "IAVGSELEN": {"bits": "22", "value": extract_bits(value, 22, 22), "meaning": "1 = IRMS averaging" if extract_bits(value, 22, 22) else "0 = VRMS averaging"},
        "PAVGSELEN": {"bits": "23", "value": extract_bits(value, 23, 23), "meaning": "1 = PACTIVE averaging" if extract_bits(value, 23, 23) else "0 = VRMS averaging path"},
    }
    if eeprom:
        add_ecc(result, value)
    return result


def decode_register_0c_1c(value: int, *, eeprom: bool) -> dict[str, Any]:
    v_offset_raw = extract_bits(value, 24, 17)
    result = {
        "RMS_AVG_1": {"bits": "6:0", "value": extract_bits(value, 6, 0)},
        "RMS_AVG_2": {"bits": "16:7", "value": extract_bits(value, 16, 7)},
        "VCHAN_OFFSET_CODE": {"bits": "24:17", "raw": v_offset_raw, "signed": sign_extend(v_offset_raw, 8)},
    }
    if eeprom:
        add_ecc(result, value)
    return result


def decode_register_0d_1d(value: int, *, eeprom: bool) -> dict[str, Any]:
    fltdly = extract_bits(value, 23, 21)
    ichan = extract_bits(value, 7, 7)
    result = {
        "ICHAN_DEL_EN": {"bits": "7", "value": ichan, "meaning": "1 = delay current channel" if ichan else "0 = delay voltage channel"},
        "CHAN_DEL_SEL": {"bits": "11:9", "value": extract_bits(value, 11, 9), "description": "Phase-delay selection; datasheet range 0 to 219 us"},
        "FAULT": {"bits": "20:13", "value": extract_bits(value, 20, 13), "description": "Overcurrent threshold code"},
        "FLTDLY": {"bits": "23:21", "value": fltdly, "delay_us": FAULT_DELAY_US[fltdly]},
    }
    if eeprom:
        add_ecc(result, value)
    return result


def decode_register_0e_1e(value: int, *, eeprom: bool) -> dict[str, Any]:
    delaycnt = extract_bits(value, 20, 20)
    result = {
        "VEVENT_CYCS": {"bits": "5:0", "raw": extract_bits(value, 5, 0), "effective_cycles": extract_bits(value, 5, 0) + 1},
        "OVERVREG": {"bits": "13:8", "value": extract_bits(value, 13, 8)},
        "UNDERVREG": {"bits": "19:14", "value": extract_bits(value, 19, 14)},
        "DELAYCNT_SEL": {"bits": "20", "value": delaycnt, "pulse_width_us": 256 if delaycnt else 32},
        "HALFCYCLE_EN": {"bits": "21", "value": extract_bits(value, 21, 21)},
        "SQUAREWAVE_EN": {"bits": "22", "value": extract_bits(value, 22, 22)},
        "ZEROCROSSCHANSEL": {"bits": "23", "value": extract_bits(value, 23, 23), "meaning": "1 = current" if extract_bits(value, 23, 23) else "0 = voltage"},
        "ZEROCROSSEDGESEL": {"bits": "24", "value": extract_bits(value, 24, 24), "meaning": "1 = rising" if extract_bits(value, 24, 24) else "0 = falling"},
    }
    if eeprom:
        add_ecc(result, value)
    return result


def decode_register_0f_1f(value: int, *, eeprom: bool) -> dict[str, Any]:
    bypass = extract_bits(value, 24, 24)
    result = {
        "I2C_SLV_ADDR": {"bits": "8:2", "value": extract_bits(value, 8, 2), "hex": f"0x{extract_bits(value, 8, 2):02X}"},
        "I2C_DIS_SLV_ADDR": {"bits": "9", "value": extract_bits(value, 9, 9)},
        "DIO_0_SEL": {"bits": "11:10", "value": extract_bits(value, 11, 10)},
        "DIO_1_SEL": {"bits": "13:12", "value": extract_bits(value, 13, 12)},
        "N": {"bits": "23:14", "value": extract_bits(value, 23, 14)},
        "BYPASS_N_EN": {"bits": "24", "value": bypass, "meaning": "1 = fixed N" if bypass else "0 = voltage-zero-crossing window"},
    }
    if eeprom:
        add_ecc(result, value)
    return result


CONFIG_DECODERS: dict[int, Callable[..., dict[str, Any]]] = {
    0x0B: decode_register_0b_1b, 0x1B: decode_register_0b_1b,
    0x0C: decode_register_0c_1c, 0x1C: decode_register_0c_1c,
    0x0D: decode_register_0d_1d, 0x1D: decode_register_0d_1d,
    0x0E: decode_register_0e_1e, 0x1E: decode_register_0e_1e,
    0x0F: decode_register_0f_1f, 0x1F: decode_register_0f_1f,
}


def decode_live_register(address: int, value: int) -> dict[str, Any]:
    if address == 0x20:
        return {
            "VRMS": {"bits": "15:0", "raw": get_integer_from_u16(value), "type": "unsigned 16-bit, 16 fractional bits"},
            "IRMS": {"bits": "31:16", "raw": get_integer_from_u16(value >> 16), "field_hex": f"0x{((value >> 16) & 0xFFFF):04X}", "type": "signed 16-bit, 16 fractional bits"},
        }
    if address == 0x21:
        return {
            "PACTIVE": {"bits": "15:0", "raw": get_integer_from_s16(value), "type": "signed 16-bit, 15 fractional bits"},
            "PIMAG": {"bits": "31:16", "raw": get_integer_from_u16(value >> 16), "type": "unsigned 16-bit, 16 fractional bits"},
        }
    if address == 0x22:
        pf_bits = extract_bits(value, 26, 16)
        posangle = extract_bits(value, 27, 27)
        pospf = extract_bits(value, 28, 28)
        return {
            "PAPPARENT": {"bits": "15:0", "raw": get_integer_from_u16(value)},
            "PFACTOR": {"bits": "26:16", "raw_11bit": pf_bits, "decoded": get_power_factor_from_11bit_register(pf_bits)},
            "POSANGLE": {"bits": "27", "value": posangle, "meaning": "1 = current lagging" if posangle else "0 = current leading"},
            "POSPF": {"bits": "28", "value": pospf, "meaning": "1 = power consumed" if pospf else "0 = power generated"},
        }
    if address == 0x25:
        return {"NUMPTSOUT": {"bits": "9:0", "value": extract_bits(value, 9, 0)}}
    if address == 0x26:
        return {
            "VRMSAVGONESEC": {"bits": "15:0", "raw": get_integer_from_u16(value)},
            "IRMSAVGONESEC": {"bits": "31:16", "raw": get_integer_from_u16(value >> 16)},
        }
    if address == 0x27:
        return {
            "VRMSAVGONEMIN": {"bits": "15:0", "raw": get_integer_from_u16(value)},
            "IRMSAVGONEMIN": {"bits": "31:16", "raw": get_integer_from_u16(value >> 16)},
        }
    if address == 0x28:
        return {"PACTAVGONESEC": {"bits": "15:0", "raw": get_integer_from_s16(value)}}
    if address == 0x29:
        return {"PACTAVGONEMIN": {"bits": "15:0", "raw": get_integer_from_s16(value)}}
    if address == 0x2A:
        return {
            "VCODES": {"bits": "15:0", "raw": get_integer_from_s16(value), "type": "signed 16-bit, 15 fractional bits"},
            "ICODES": {"bits": "31:16", "raw": get_integer_from_s16(value >> 16), "type": "signed 16-bit, 15 fractional bits"},
        }
    if address == 0x2C:
        return {"PINSTANT": {"bits": "15:0", "raw": get_integer_from_s16(value), "type": "signed 16-bit, 15 fractional bits"}}
    if address == 0x2D:
        return {
            "ZEROCROSSOUT": {"bits": "0", "value": extract_bits(value, 0, 0)},
            "FAULTOUT": {"bits": "1", "value": extract_bits(value, 1, 1)},
            "FAULTLATCHED": {"bits": "2", "value": extract_bits(value, 2, 2), "note": "This script does not clear it"},
            "OVERVOLTAGE": {"bits": "3", "value": extract_bits(value, 3, 3)},
            "UNDERVOLTAGE": {"bits": "4", "value": extract_bits(value, 4, 4)},
        }
    return {}


def read_configuration(bus: SMBus) -> dict[str, Any]:
    eeprom: dict[str, Any] = {}
    shadow: dict[str, Any] = {}
    for address, name in EEPROM_REGISTERS.items():
        value = get_32_bit_little_endian(bus, address)
        record = raw_record(address, name, value)
        record["decoded"] = CONFIG_DECODERS[address](value, eeprom=True)
        eeprom[f"0x{address:02X}"] = record
    for address, name in SHADOW_REGISTERS.items():
        value = get_32_bit_little_endian(bus, address)
        record = raw_record(address, name, value)
        record["decoded"] = CONFIG_DECODERS[address](value, eeprom=False)
        shadow[f"0x{address:02X}"] = record

    comparison: dict[str, Any] = {}
    mask_26_bits = (1 << 26) - 1
    for eeprom_address in range(0x0B, 0x10):
        shadow_address = eeprom_address + 0x10
        ev = eeprom[f"0x{eeprom_address:02X}"]["raw_unsigned"]
        sv = shadow[f"0x{shadow_address:02X}"]["raw_unsigned"]
        comparison[f"0x{eeprom_address:02X}_vs_0x{shadow_address:02X}"] = {
            "eeprom_configuration_hex": f"0x{ev & mask_26_bits:07X}",
            "shadow_configuration_hex": f"0x{sv & mask_26_bits:07X}",
            "configuration_bits_25_0_match": (ev & mask_26_bits) == (sv & mask_26_bits),
        }
    return {"eeprom": eeprom, "shadow": shadow, "eeprom_shadow_comparison": comparison}


def read_live_snapshot(bus: SMBus) -> dict[str, Any]:
    registers: dict[str, Any] = {}
    for address, name in LIVE_REGISTERS.items():
        value = get_32_bit_little_endian(bus, address)
        record = raw_record(address, name, value)
        record["decoded"] = decode_live_register(address, value)
        registers[f"0x{address:02X}"] = record
    return {"timestamp": datetime.now().isoformat(timespec="milliseconds"), "registers": registers}


def read_instantaneous_burst(bus: SMBus, sample_count: int, sample_delay_s: float) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for index in range(sample_count):
        raw_vi = get_32_bit_little_endian(bus, 0x2A)
        raw_p = get_32_bit_little_endian(bus, 0x2C)
        samples.append({
            "index": index,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "VCODES": get_integer_from_s16(raw_vi),
            "ICODES": get_integer_from_s16(raw_vi >> 16),
            "PINSTANT": get_integer_from_s16(raw_p),
            "raw_0x2A_hex": f"0x{raw_vi:08X}",
            "raw_0x2C_hex": f"0x{raw_p:08X}",
        })
        if sample_delay_s > 0 and index < sample_count - 1:
            time.sleep(sample_delay_s)
    return samples


def print_configuration_summary(configuration: dict[str, Any]) -> None:
    print("\n=== EEPROM AND SHADOW CONFIGURATION ===")
    for section_name in ("eeprom", "shadow"):
        print(f"\n{section_name.upper()}")
        for address, record in configuration[section_name].items():
            print(f"  {address}  {record['raw_hex']}  {record['name']}")

    print("\nEEPROM/SHADOW CONFIGURATION-BIT COMPARISON")
    for pair, result in configuration["eeprom_shadow_comparison"].items():
        status = "MATCH" if result["configuration_bits_25_0_match"] else "DIFFER"
        print(f"  {pair}: {status}  EEPROM={result['eeprom_configuration_hex']}  shadow={result['shadow_configuration_hex']}")

    current_shadow = configuration["shadow"]["0x1B"]["decoded"]
    print("\nKEY CURRENT-CHANNEL SETTINGS FROM SHADOW 0x1B")
    print(f"  QVO_FINE : signed={current_shadow['QVO_FINE']['signed']} raw={current_shadow['QVO_FINE']['raw']}")
    print(f"  SNS_FINE : signed={current_shadow['SNS_FINE']['signed']} raw={current_shadow['SNS_FINE']['raw']}")
    print(f"  CRS_SNS  : code={current_shadow['CRS_SNS']['raw']} gain={current_shadow['CRS_SNS']['gain_multiplier']}x")


def print_live_snapshot(snapshot: dict[str, Any]) -> None:
    regs = snapshot["registers"]
    r20, r21, r22 = regs["0x20"]["decoded"], regs["0x21"]["decoded"], regs["0x22"]["decoded"]
    r25, r2d = regs["0x25"]["decoded"], regs["0x2D"]["decoded"]
    print(f"\n=== LIVE SNAPSHOT {snapshot['timestamp']} ===")
    print(f"0x20 {regs['0x20']['raw_hex']}  VRMS={r20['VRMS']['raw']}  IRMS={r20['IRMS']['raw']} [field {r20['IRMS']['field_hex']}]")
    print(f"0x21 {regs['0x21']['raw_hex']}  PACTIVE={r21['PACTIVE']['raw']}  PIMAG={r21['PIMAG']['raw']}")
    print(f"0x22 {regs['0x22']['raw_hex']}  PAPPARENT={r22['PAPPARENT']['raw']}  PF={r22['PFACTOR']['decoded']:+.6f}  POSANGLE={r22['POSANGLE']['value']}  POSPF={r22['POSPF']['value']}")
    print(f"0x25 {regs['0x25']['raw_hex']}  NUMPTSOUT={r25['NUMPTSOUT']['value']}")
    print(f"0x2D {regs['0x2D']['raw_hex']}  ZC={r2d['ZEROCROSSOUT']['value']} FAULT={r2d['FAULTOUT']['value']} LATCHED={r2d['FAULTLATCHED']['value']} OV={r2d['OVERVOLTAGE']['value']} UV={r2d['UNDERVOLTAGE']['value']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only ACS37800 power-chip diagnostic utility")
    parser.add_argument("--samples", type=int, default=10, help="Complete live snapshots (default: 10)")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between snapshots (default: 0.5)")
    parser.add_argument("--burst-samples", type=int, default=100, help="Instantaneous samples (default: 100)")
    parser.add_argument("--burst-delay", type=float, default=0.0, help="Seconds between instantaneous samples (default: 0)")
    parser.add_argument("--output-folder", type=Path, default=OUTPUT_FOLDER, help="JSON output folder")
    return parser.parse_args()