"""Public API for water-valve control."""

# This __init__ will serve as a sub-package API for the consumers that require valve services.

# Public bounds:

# - Valve protocol from `software/valve/valve_interface.py`
# - `build_gpio_valve()` function `software/valve/gpio_valve_builder.py`

# Private bounds:

# - Hardware controlling GPIO driver
# - GPIO implementation details e.g. addresses and values
# - Pin constants
# - Station mapping
# - Other valve diagnostic functions intended for developing or troubleshooting, not
#standard runtime operation


from .gpio_valve_builder import build_gpio_valve
from .valve_interface import Valve

__all__ = ["Valve", "build_gpio_valve"]
