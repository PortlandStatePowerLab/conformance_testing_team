#!/usr/bin/env python3
from smbus2 import SMBus
import time, json, os
from datetime import datetime

# -----------------------------
# Helpers
# -----------------------------
from helpers.helper_power_functions import (
    get_integer_from_u16,
    get_integer_from_s16,
    get_32_bit_little_endian,
    get_power_data,
    get_power_factor_from_11bit_register,
    get_calibration_from_JSON,
    set_calibration,
    read_measurement_values,
    calibrate,
    get_pi_number,
)

from helpers.hardware_map import (
        I2C_BUS,
)

pi_number = get_pi_number()

# Folder/file locations
OUTPUT_FOLDER = os.path.join(os.path.expanduser("../"), "saved_data")
CALIBRATION_DIR = os.path.join(OUTPUT_FOLDER, "calibration")

def main():
    """Run the main logging loop for the ACS37800 sensor.

    This function sets up the output folder and CSV file, optionally performs
    calibration, then enters a loop reading measurements every second and
    writing them to both stdout and the CSV log file.
    """
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    calibration = get_calibration_from_JSON(CALIBRATION_DIR, OUTPUT_FOLDER)

    csv_name = datetime.now().strftime("power_data_%Y_%m_%d_%Hh%Mm%S.csv")
    csv_path = os.path.join(OUTPUT_FOLDER, csv_name)

    with SMBus(I2C_BUS) as bus, open(csv_path, "w") as f:
        f.write("time,vrms,irms,real_power,reactive_power,apparent_power,pf,vrms_raw,irms_raw,real_power_raw,pimag_raw,papparent_raw\n")
        print(f"Logging to: {csv_path}")
        print("Commands:")
        print("  c  -> full calibration (recommended)")
        print("  Enter -> start using saved calibration\n")
        cmd = input("> ").strip().lower()
        if cmd == "c":
            calibrate(bus, calibration, CALIBRATION_DIR, OUTPUT_FOLDER)

        calibration = get_calibration_from_JSON(CALIBRATION_DIR, OUTPUT_FOLDER)

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
        #print(f"Power data: {get_power_data(bus, calibration)}")

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
                real_power = measurement["real_power"]
                reactive_power = measurement["reactive_power"]
                apparent_power = measurement["apparent_power"]
                power_factor = measurement["power_factor"]

                voltage_rms_text = "None" if voltage_rms is None else f"{voltage_rms:.1f}"
                current_rms_text = "None" if current_rms is None else f"{current_rms:.2f}"
                real_power_text = "None" if real_power is None else f"{real_power:.1f}"
                reactive_power_text = "None" if reactive_power is None else f"{measurement['reactive_power']:.1f}"
                apparent_power_text = "None" if apparent_power is None else f"{measurement['apparent_power']:.1f}"

                print(f"{t}  Vrms={voltage_rms_text}  Irms={current_rms_text}  P={real_power_text} W  Q={reactive_power_text} VAR  S={apparent_power_text} VA  PF={power_factor:+.3f}  "
                      f"(raw vr={measurement['voltage_rms_raw']} ir={measurement['current_rms_raw']})")

                f.write(f"{t},{voltage_rms if voltage_rms is not None else ''},{current_rms if current_rms is not None else ''},"
                        f"{real_power if real_power is not None else ''},{power_factor},"
                        f"{measurement['voltage_rms_raw']},{measurement['current_rms_raw']},{measurement['real_power_raw']},"
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
