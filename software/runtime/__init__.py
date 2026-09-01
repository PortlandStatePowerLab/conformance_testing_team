"""Public API for manually invoked station runtime workflows."""

# This initializer serves as the runtime subpackage API for consumers that run
# manual station commissioning workflows.
#
# Public bounds:
# - run_controlled_water_draw() workflow from
#   software/runtime/controlled_water_draw_workflow.py
#
# Private bounds:
# - Sensor-reader protocol used internally by the workflow
# - Maximum-runtime, minimum-flow, low-flow-timeout, and print-period settings
# - Volume-integration and workflow-loop implementation details
# - Command-line parsing and operator entrypoints
# - Sensor, ADC, and valve hardware construction

from .controlled_water_draw_workflow import run_controlled_water_draw

__all__ = ["run_controlled_water_draw"]
