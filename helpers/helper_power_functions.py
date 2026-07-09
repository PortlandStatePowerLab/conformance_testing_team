#!/usr/bin/env python3
from smbus2 import SMBus
import time, json, os, re, socket
from datetime import datetime

from helpers.hardware_map import (
        I2C_BUS,
        SENSOR_ADDRESS,
        REG_VRMS_REGISTER,
        REG_POWER_REGISTER,
        REG_POWER_FACTOR_REGISTER,
        NOISE_FLOOR_VRMS_CODES,
        NOISE_FLOOR_IRMS_CODES,
        NOISE_FLOOR_V_VOLTS,
        NOISE_FLOOR_I_AMPS,
        POWER_ABS,
)

# These are helper functions specific to capturing and caclulating power elements

def get_pi_number():
    # Get the current hostname safely
    hostname = socket.gethostname()  # e.g., "WH-station12"

    # Match one or more digits strictly at the end of the string
    result = re.search(r'\d+$', hostname)

    if result:
        # Extract the full string match and convert to an integer
        #station_number = int(station_match.group())
        print(f"Verified station number: {result}")
        return result.group()        
    else:
        print("ERROR: Could not find a station number at the end of the hostname.")

def get_integer_from_u16(x):
    """Convert an integer to an unsigned 16-bit value.

    This masks the input to the lower 16 bits and returns the result.
    Used to parse unsigned register fields from the 32-bit device registers.
    """
    return x & 0xFFFF

def get_integer_from_s16(x):
    """Convert an integer to a signed 16-bit value.

    This masks the input to 16 bits and applies two's complement
    conversion so negative raw register values are returned correctly.
    """
    x &= 0xFFFF
    return x - 0x10000 if (x & 0x8000) else x

def get_32_bit_little_endian(bus, reg):
    """Read a 32-bit little-endian register from the ACS37800 sensor.

    Returns the combined 32-bit value or None if the I2C transaction fails.
    """
    try:
        b = bus.read_i2c_block_data(SENSOR_ADDRESS, reg, 4)
    except Exception:
        return None
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

def get_power_factor_from_11bit_register(raw_power_factor_bits):
    """Decode the ACS37800 power-factor field from its 11-bit register value.

    The chip stores power factor as a signed 11-bit value with 10 fractional
    bits, so the decoded result is approximately in the range -1.0 to +1.0.
    """
    decoded_value = raw_power_factor_bits & 0x7FF
    if decoded_value & 0x400:
        decoded_value -= 0x800
    return decoded_value / (2**10)

def _get_default_calibration():
    return {
        # scales convert (raw - offset) -> engineering units
        "vrms_scale": None,     # V per code
        "irms_scale": None,     # A per code
        # offsets are captured raw baselines
        "vrms_offset": 0,       # VRMS_raw at 0V (mains/transformer off but chip powered)
        "irms_offset": 0,       # IRMS_raw at 0A (voltage present but no load)
        # human-readable engineering offsets
        "vrms_offset_volts": 0.0,
        "irms_offset_amps": 0.0,
        # saved metadata
        "last_cal_time": None,
        "line_vrms_used": None,
        "clamp_irms_used": None
    }


def get_calibration_from_JSON(CALIBRATION_FILE_PATH, OUTPUT_FOLDER):
    """Load calibration settings for the current Pi from disk.

    Reads a host-keyed JSON calibration file if it exists and returns the
    calibration dictionary for the current hostname. If the file is in the
    legacy single-profile format, it will still be read for compatibility.
    """
    calibration = _get_default_calibration()
    host_name = socket.gethostname()

    if not os.path.exists(CALIBRATION_FILE_PATH):
        return calibration

    try:
        with open(CALIBRATION_FILE_PATH, "r", encoding="utf-8") as f:
            loaded_data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: could not load calibration file {CALIBRATION_FILE_PATH}: {exc}")
        return calibration

    if isinstance(loaded_data, dict):
        if all(key in loaded_data for key in ("vrms_scale", "irms_scale", "vrms_offset", "irms_offset")):
            return loaded_data
        if host_name in loaded_data and isinstance(loaded_data[host_name], dict):
            return loaded_data[host_name]

    return calibration


def set_calibration(calibration, CALIBRATION_FILE_PATH, OUTPUT_FOLDER, hostname=None):
    """Persist calibration settings to disk for the current Pi.

    Writes the current calibration dictionary into a host-keyed JSON object so
    each Pi can keep its own calibration profile.
    """
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    host_name = hostname or socket.gethostname()

    existing_profiles = {}
    if os.path.exists(CALIBRATION_FILE_PATH):
        try:
            with open(CALIBRATION_FILE_PATH, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
            if isinstance(loaded_data, dict):
                if all(key in loaded_data for key in ("vrms_scale", "irms_scale", "vrms_offset", "irms_offset")):
                    existing_profiles = {}
                else:
                    existing_profiles = {k: v for k, v in loaded_data.items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: could not load existing calibration file {CALIBRATION_FILE_PATH}: {exc}")

    existing_profiles[host_name] = calibration

    with open(CALIBRATION_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_profiles, f, indent=2)
        f.write("\n")

def read_measurement_values(bus, calibration):
    """Read raw sensor registers and convert them into engineering values.

    Fetches the three ACS37800 registers needed for voltage, current,
    power, and power factor. Applies raw-domain offset clamping and scaling
    using the loaded calibration data. Returns a dictionary containing both
    raw codes and converted values.
    """
    raw_rms_register = get_32_bit_little_endian(bus, REG_VRMS_REGISTER)
    raw_power_register = get_32_bit_little_endian(bus, REG_POWER_REGISTER)
    raw_power_factor_register = get_32_bit_little_endian(bus, REG_POWER_FACTOR_REGISTER)

    if (raw_rms_register is None) or (raw_power_register is None) or (raw_power_factor_register is None):
        return None

    vrms_raw = get_integer_from_u16(raw_rms_register)
    irms_raw = get_integer_from_s16(raw_rms_register >> 16)

    pactive_raw = get_integer_from_s16(get_integer_from_u16(raw_power_register))
    pimag_raw = get_integer_from_u16(raw_power_register >> 16)

    papparent_raw = get_integer_from_u16(raw_power_factor_register)
    pf_11bit = (raw_power_factor_register >> 16) & 0x7FF
    pf = get_power_factor_from_11bit_register(pf_11bit)

    # ---------- Raw-domain clamping (prevents floating-input ghosts) ----------
    vrms_offset_raw = int(calibration.get("vrms_offset", 0))
    irms_offset_raw = int(calibration.get("irms_offset", 0))

    if abs(vrms_raw - vrms_offset_raw) < NOISE_FLOOR_VRMS_CODES:
        vrms_raw = vrms_offset_raw

    if abs(irms_raw - irms_offset_raw) < NOISE_FLOOR_IRMS_CODES:
        irms_raw = irms_offset_raw
    # ------------------------------------------------------------------------

    vrms = None
    if calibration["vrms_scale"] is not None:
        vrms = (vrms_raw - vrms_offset_raw) * float(calibration["vrms_scale"])

    irms = None
    if calibration["irms_scale"] is not None:
        irms = (irms_raw - irms_offset_raw) * float(calibration["irms_scale"])

    # Engineering-domain clamping
    if vrms is not None and vrms < NOISE_FLOOR_V_VOLTS:
        vrms = 0.0
    if irms is not None and abs(irms) < NOISE_FLOOR_I_AMPS:
        irms = 0.0

    # Power estimate using PF from chip
    estimated_power = None
    if (vrms is not None) and (irms is not None):
        estimated_power = vrms * irms * pf
        if POWER_ABS:
            estimated_power = abs(estimated_power)

    return {
        "voltage_rms_raw": vrms_raw,
        "current_rms_raw": irms_raw,
        "active_power_raw": pactive_raw,
        "reactive_power_raw": pimag_raw,
        "apparent_power_raw": papparent_raw,
        "power_factor": pf,
        "voltage_rms": vrms,
        "current_rms": irms,
        "estimated_power": estimated_power,
    }

def calibrate(bus, calibration, CALIBRATION_FILE_PATH, OUTPUT_FOLDER, hostname=None):
    """Perform interactive calibration for voltage and current scaling.

    This function prompts the user to capture the zero-offset values for
    the sensor at 0V and 0A, then asks for known true values so it can
    compute the VRMS and IRMS scale factors.
    """
    print("\n=== Calibration (Aligned to your setup) ===")
    print("NOTE: Your chip is powered by separate supply.")
    print("We will capture TWO baselines:")
    print("  A) VRMS offset at 0V (mains/transformer OFF, chip still powered)")
    print("  B) IRMS offset at 0A (voltage present, heater OFF / no load)")
    print("Then we capture two scales (240V and clamp current).\n")

    # A) Capture VRMS offset at 0V
    print("A) VRMS offset (0V): Turn OFF mains/transformer so VINP should be ~0V.")
    input("Press Enter to capture VRMS_raw offset (0V)...")
    values = read_measurement_values(bus, calibration)
    if values is None:
        print("I2C read failed. Check wiring/address.")
        return
    calibration["vrms_offset"] = int(values["voltage_rms_raw"])
    if calibration.get("vrms_scale") is not None:
        calibration["vrms_offset_volts"] = float(calibration["vrms_offset"]) * float(calibration["vrms_scale"])
    else:
        calibration["vrms_offset_volts"] = 0.0
    print(f"Captured VRMS offset = {calibration['vrms_offset']} raw codes")

    # B) Capture IRMS offset at 0A with voltage present
    print("\nB) IRMS offset (0A): Turn ON mains (voltage present), but ensure NO LOAD (heater OFF).")
    input("Press Enter to capture IRMS_raw offset (0A)...")
    values = read_measurement_values(bus, calibration)
    if values is None:
        print("I2C read failed. Check wiring/address.")
        return
    calibration["irms_offset"] = int(values["current_rms_raw"])
    if calibration.get("irms_scale") is not None:
        calibration["irms_offset_amps"] = float(calibration["irms_offset"]) * float(calibration["irms_scale"])
    else:
        calibration["irms_offset_amps"] = 0.0
    print(f"Captured IRMS offset = {calibration['irms_offset']} raw codes")

    # Voltage scale
    print("\nC) Voltage scale: keep mains ON (normal operation).")
    true_line_voltage = float(input("Enter the true line voltage in volts (for example, 240): ").strip())
    input("Press Enter to capture the voltage reading for scaling...")
    values = read_measurement_values(bus, calibration)
    if values is None:
        print("I2C read failed. Check wiring/address.")
        return
    raw_voltage_rms = int(values["voltage_rms_raw"])
    voltage_difference = float(raw_voltage_rms - calibration["vrms_offset"])
    if abs(voltage_difference) < 10:
        print("VRMS_raw - vrms_offset is too small. Is mains really ON? Is VINP driven?")
        return
    calibration["vrms_scale"] = true_line_voltage / voltage_difference
    calibration["line_vrms_used"] = true_line_voltage
    calibration["vrms_offset_volts"] = float(calibration["vrms_offset"]) * float(calibration["vrms_scale"])
    print(f"VRMS_raw={raw_voltage_rms} => vrms_scale={calibration['vrms_scale']:.10f} V/code")

    # Current scale
    print("\nD) Current scale: turn ON heater so current flows. Use a clamp meter.")
    true_load_current = float(input("Enter the true load current in amps from the clamp meter (for example, 18.7): ").strip())
    input("Press Enter to capture the current reading under load...")
    values = read_measurement_values(bus, calibration)
    if values is None:
        print("I2C read failed. Check wiring/address.")
        return
    raw_current_rms = int(values["current_rms_raw"])
    current_difference = float(raw_current_rms - calibration["irms_offset"])
    if abs(current_difference) < 10:
        print("IRMS_raw - irms_offset is too small. Increase load and try again.")
        return
    calibration["irms_scale"] = true_load_current / current_difference
    calibration["clamp_irms_used"] = true_load_current
    calibration["irms_offset_amps"] = float(calibration["irms_offset"]) * float(calibration["irms_scale"])
    print(f"IRMS_raw={raw_current_rms} => irms_scale={calibration['irms_scale']:.10f} A/code")

    calibration["last_cal_time"] = datetime.now().isoformat(timespec="seconds")

    if os.path.exists(CALIBRATION_FILE_PATH):
        overwrite = input(
            f"Calibration file already exists at {CALIBRATION_FILE_PATH}. Overwrite it? (y/N): "
        ).strip().lower()
        if overwrite not in {"y", "yes"}:
            print("Calibration was not saved.")
            return

    set_calibration(calibration, CALIBRATION_FILE_PATH, OUTPUT_FOLDER, hostname=hostname)
    print(f"\nSaved calibration to: {CALIBRATION_FILE_PATH}\n")

