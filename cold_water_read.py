import subprocess
import json
from pathlib import Path

config_path = ("secrets/pi_config.json")

with open(config_path, "r") as f:
    config = json.load(f)

PI1_HOST = config["pi1_host"]

proc = subprocess.Popen(
    [
        "ssh",
        PI1_HOST,
        "python",
        "/home/pi/cold_water_stream.py"
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

try:
    # Define column headers and widths (15 characters wide each)
    for line in proc.stdout:
        data = json.loads(line.strip())
        cold_temp_c = data["cold_water_temp_c"]
        cold_temp_f = data["cold_water_temp_c"]*1.8+32
        print(f"{'Cold water temp:':<16} {cold_temp_c:>8.2f}°C {cold_temp_f:>8.2f}°F")
        # Your water draw code can use cold_temp_c here

except KeyboardInterrupt:
    pass

finally:
     proc.terminate()

     try:
         proc.wait(timeout=3)
     except subprocess.TimeoutExpired:
         proc.kill()
