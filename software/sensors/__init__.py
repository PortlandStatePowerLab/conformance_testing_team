"""Public API for sensor information"""

# This __init__ will serve as a sub-package API for the consumers that require sensor information.
#
# Public bounds:
#
# - `SensorReader` service from `software/sensors/sensor_reader.py`
# - `SensorSnapshot` data structure from `software/sensors/sensor_reader.py`
#
# Private bounds:
#
# - Sensor conversion math and configuration loading
# - Station sensor-channel assignments
# - Sensor diagnostic functions intended for development or troubleshooting, not standard
#   runtime operation
# - Legacy sensor helpers and hardware-specific implementation details

from .sensor_reader import SensorReader, SensorSnapshot

__all__ = ["SensorReader", "SensorSnapshot"]
