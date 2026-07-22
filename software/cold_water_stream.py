import time
import json
import signal
import sys
from WaterHeaterStation.max1238 import Max1238, InputMode

VREF = 4.096
AREF = 4096.0
R_SHUNT_OHMS = 120.0
T_MAX_C = 150.0
T_MIN_C = -50.0
CH_COLD = 0

running = True

def stop_handler(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

def raw_to_volts(raw: int) -> float:
    return (raw / AREF) * VREF

def volts_to_temp(val_v: float) -> float:
    i_loop = max(val_v / R_SHUNT_OHMS, 0.0)
    norm = (i_loop - 4e-3) / 16e-3
    return (norm * (T_MAX_C - T_MIN_C)) + T_MIN_C

def main():
    adc = Max1238()
    adc.setup_adc()

    while running:
        raw = adc.read_single(CH_COLD)
        volts = raw_to_volts(raw)
        temp_c = volts_to_temp(volts)

        data = {
            "cold_water_temp_c": temp_c,
            "cold_water_volts": volts,
            "raw": raw,
            "timestamp": time.time()
        }

        try:
            print(json.dumps(data), flush=True)
        except BrokenPipeError:
            break

        time.sleep(0.5)

    sys.exit(0)

if __name__ == "__main__":
    main()
