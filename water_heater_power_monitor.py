#!/usr/bin/env python3
from smbus2 import SMBus
import time, json, os
from datetime import datetime

# -----------------------------
# User setup (your confirmed)
# -----------------------------
SENSOR_ADDRESS = 0x60
I2C_BUS = 1

# 32-bit little-endian registers
REG_VRMS_REGISTER = 0x20   # [15:0]=VRMS(u16), [31:16]=IRMS(s16)
REG_POWER_REGISTER = 0x21 # [15:0]=PACTIVE(s16), [31:16]=PIMAG(u16)
REG_POWER_FACTOR_REGISTER = 0x22 # [15:0]=PAPP(u16), [26:16]=PF(11b signed), bit27 posangle, bit28 pospf

# Folder/file locations
OUTPUT_FOLDER = os.path.join(os.path.expanduser("./"), "saved_data")
CALIBRATION_FILE_PATH = os.path.join(OUTPUT_FOLDER, "water_heater_calibration.json")

# Noise floors (tune if needed)
# These prevent "ghost" readings when VINP/inputs float (chip powered but mains/load removed)
NOISE_FLOOR_VRMS_CODES = 300    # raw codes near baseline treated as 0V
NOISE_FLOOR_IRMS_CODES = 80     # raw codes near baseline treated as 0A
NOISE_FLOOR_V_VOLTS    = 5.0    # Vrms below this -> show 0.0
NOISE_FLOOR_I_AMPS     = 0.20   # Irms below this -> show 0.0

# Power sign handling:
# If you want consumed power always positive, keep POWER_ABS=True
POWER_ABS = True


# -----------------------------
# Helpers
# -----------------------------
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

def get_calibration_from_JSON():
    """Load calibration settings from disk.

    Reads the JSON calibration file if it exists and returns a dictionary
    containing scale and offset values needed to convert raw sensor codes
    into engineering units.
    """
    calibration = {
        # scales convert (raw - offset) -> engineering units
        "vrms_scale": None,     # V per code
        "irms_scale": None,     # A per code
        # offsets are captured raw baselines
        "vrms_offset": 0,       # VRMS_raw at 0V (mains/transformer off but chip powered)
        "irms_offset": 0,       # IRMS_raw at 0A (voltage present but no load)
        # saved metadata
        "last_cal_time": None,
        "line_vrms_used": None,
        "clamp_irms_used": None
    }
    if not os.path.exists(CALIBRATION_FILE_PATH):
        return calibration

    try:
        with open(CALIBRATION_FILE_PATH, "r", encoding="utf-8") as f:
            calibration.update(json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: could not load calibration file {CALIBRATION_FILE_PATH}: {exc}")

    return calibration

def set_calibration(calibration):
    """Persist calibration settings to disk.

    Writes the current calibration dictionary to the configured JSON file
    so future runs can reuse the measured scale and offset values.
    """
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    with open(CALIBRATION_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2)
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
    irms_raw = get_integer_from_u16(raw_rms_register >> 16)

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

def calibrate(bus, calibration):
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
    print(f"Captured VRMS offset = {calibration['vrms_offset']} raw codes")

    # B) Capture IRMS offset at 0A with voltage present
    print("\nB) IRMS offset (0A): Turn ON mains (voltage present), but ensure NO LOAD (heater OFF).")
    input("Press Enter to capture IRMS_raw offset (0A)...")
    values = read_measurement_values(bus, calibration)
    if values is None:
        print("I2C read failed. Check wiring/address.")
        return
    calibration["irms_offset"] = int(values["current_rms_raw"])
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
    print(f"IRMS_raw={raw_current_rms} => irms_scale={calibration['irms_scale']:.10f} A/code")

    calibration["last_cal_time"] = datetime.now().isoformat(timespec="seconds")

    if os.path.exists(CALIBRATION_FILE_PATH):
        overwrite = input(
            f"Calibration file already exists at {CALIBRATION_FILE_PATH}. Overwrite it? (y/N): "
        ).strip().lower()
        if overwrite not in {"y", "yes"}:
            print("Calibration was not saved.")
            return

    set_calibration(calibration)
    print(f"\nSaved calibration to: {CALIBRATION_FILE_PATH}\n")


def main():
    """Run the main logging loop for the ACS37800 sensor.

    This function sets up the output folder and CSV file, optionally performs
    calibration, then enters a loop reading measurements every second and
    writing them to both stdout and the CSV log file.
    """
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    calibration = get_calibration_from_JSON()

    csv_name = datetime.now().strftime("power_data_%Y_%m_%d_%H%M%S.csv")
    csv_path = os.path.join(OUTPUT_FOLDER, csv_name)

    with SMBus(I2C_BUS) as bus, open(csv_path, "w") as f:
        f.write("time,vrms,irms,p_est,pf,vrms_raw,irms_raw,pactive_raw,pimag_raw,papparent_raw\n")
        print(f"Logging to: {csv_path}")
        print("Commands:")
        print("  c  -> full calibration (recommended)")
        print("  Enter -> start using saved calibration\n")
        cmd = input("> ").strip().lower()
        if cmd == "c":
            calibrate(bus, calibration)

        calibration = get_calibration_from_JSON()

        try:
            runtime_hours = int(input("Run for how many hours? ").strip())
            runtime_minutes = int(input("Run for how many minutes? ").strip())
        except ValueError:
            print("Invalid input. Using default runtime of 1 hour.")
            runtime_hours = 1
            runtime_minutes = 0

        run_duration_seconds = runtime_hours * 3600 + runtime_minutes * 60
        start_time = datetime.now()
        elapsed_seconds = 0

        try:
            while elapsed_seconds < run_duration_seconds:
                t = datetime.now().isoformat(timespec="seconds")
                measurement = read_measurement_values(bus, calibration)

                if measurement is None:
                    print(f"{t}  I2C READ ERROR")
                    time.sleep(1)
                    continue

                voltage_rms = measurement["voltage_rms"]
                current_rms = measurement["current_rms"]
                estimated_power = measurement["estimated_power"]
                power_factor = measurement["power_factor"]

                voltage_rms_text = "None" if voltage_rms is None else f"{voltage_rms:.2f}"
                current_rms_text = "None" if current_rms is None else f"{current_rms:.2f}"
                estimated_power_text = "None" if estimated_power is None else f"{estimated_power:.1f}"

                print(f"{t}  Vrms={voltage_rms_text}  Irms={current_rms_text}  P={estimated_power_text} W  PF={power_factor:+.3f}  "
                      f"(raw vr={measurement['voltage_rms_raw']} ir={measurement['current_rms_raw']})")

                f.write(f"{t},{voltage_rms if voltage_rms is not None else ''},{current_rms if current_rms is not None else ''},"
                        f"{estimated_power if estimated_power is not None else ''},{power_factor},"
                        f"{measurement['voltage_rms_raw']},{measurement['current_rms_raw']},{measurement['active_power_raw']},"
                        f"{measurement['reactive_power_raw']},{measurement['apparent_power_raw']}\n")
                f.flush()

                elapsed_seconds = (datetime.now() - start_time).total_seconds()
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\nStopped by user (Ctrl+C). Data saved to: {csv_path}")
            return

        print(f"Completed run after {runtime_hours} hour(s) and {runtime_minutes} minute(s).")


if __name__ == "__main__":
    main()
