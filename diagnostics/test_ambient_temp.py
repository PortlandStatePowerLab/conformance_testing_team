#!/usr/bin/env python3
import atexit
import signal
import sys
import time

import RPi.GPIO as GPIO
from max1238 import Max1238

# GPIO Pins
VALVE_PIN = 17

# MAX1238 channels
CH_HOT = 0
CH_COLD = 3 # Still Not Impl on hardware
CH_FLOW = 2
CH_AMBIENT = 4

# ADC config
ADC_VREF = 4.096
ADC_MAX = (2**12) - 1

R_SHUNT_OHMS = 120.0

# Temperature transmitters C)
T_MAX_C = 150.0
T_MIN_C = -50.0

# Flow transmitter (GPM)
Q_MAX_GPM = 10.0
Q_MIN_GPM = 0

# Fail-safe configuration
MAX_RUN_MINUTES = 5.0
MIN_FLOW_GPM = 0.05
LOW_FLOW_TIMEOUT_S = 20.0
PRINT_PERIOD_S = 0.5

# Init
GPIO.setmode(GPIO.BCM)
GPIO.setup(VALVE_PIN, GPIO.OUT, initial=GPIO.LOW)

adc = Max1238()
adc.setup_adc()


def _raw_to_voltage(raw: int) -> float:
    if raw is None:
        return float("nan")
    return (float(raw) / ADC_MAX) * ADC_VREF


def _volt_to_span(val_v: float, span_max: float, span_min: float) -> float:
    if val_v != val_v:
        return float("nan")

    i_loop = val_v / R_SHUNT_OHMS
    if i_loop < 0:
        i_loop = 0.0

    norm = (i_loop - 4e-3) / 16e-3
    return (norm * (span_max - span_min)) + span_min


def read_voltage(channel: int) -> float:
    raw = adc.read_single(channel)
    return _raw_to_voltage(raw)


def read_amb_temps() -> float:
    return read_voltage(CH_AMBIENT) / 10e-3


def draw_water():
    start = time.monotonic()
    last_log = start
   
    try:
        t_prev = time.monotonic()
        while True:
            now = time.monotonic()
            dt = now - t_prev
            t_prev = now

            if (now - start) > (MAX_RUN_MINUTES * 60.0):
                print("[!] Timeout reached. Stopping.")
                break

            amb_temps = read_amb_temps()
            amb_temps_F = amb_temps*1.8+32
       
            if (now - last_log) >= PRINT_PERIOD_S:
                print(
                    f"T_amb={amb_temps:.1f} C  "
                    f"T_amb_F={amb_temps_F:.1f} F "
                )
                last_log = now

            time.sleep(0.05)

    except Exception as e:
        print(f"[!] Exception: {e}")
   

if __name__ == "__main__":
    try:
        draw_water()
    except KeyboardInterrupt:
        print("\n[!] Aborted by user.")
