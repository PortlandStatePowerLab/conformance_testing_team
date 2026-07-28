"""Canonical CTA-2045 SGD operational-state codes."""

from __future__ import annotations


OPERATIONAL_STATE_NAMES = {
    0: "Idle Normal",
    1: "Running Normal",
    2: "Running Curtailed",
    3: "Running Heightened",
    4: "Idle Curtailed",
    5: "SGD Error Condition",
    6: "Idle Heightened",
    7: "Cycling on",
    8: "Cycling off",
    9: "Variable Following",
    10: "Variable not following",
    11: "Idle, opted out",
    12: "Running, opted out",
    13: "Running, price stream",
    14: "Idle, price stream",
}

EXPECTED_STATES_BY_ACTION = {
    "load_up": (3, 6),
    "advanced_load_up": (3, 6),
    "run_normal": (0, 1),
    "shed": (2, 4),
    "critical_peak": (2, 4),
    "grid_emergency": (2, 4),
}


def operational_state_name(code: int) -> str:
    return OPERATIONAL_STATE_NAMES.get(code, f"Unknown state ({code})")
