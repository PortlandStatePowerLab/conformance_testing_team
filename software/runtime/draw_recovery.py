"""Operating-state driven recovery and final observation after a water draw."""

from __future__ import annotations

OBSERVATION_SECONDS = 30 * 60
RECOVERY_TIMEOUT_SECONDS = 12 * 60 * 60
STATE_FRESHNESS_SECONDS = 120
RUNNING_STATES = {1, 2, 3, 7, 12, 13}
IDLE_STATES = {0, 4, 6, 8, 11, 14}


class DrawRecovery:
    """Follow just the first heating phase; never extend for subsequent cycles.

    A fresh valid state is required before making a transition. Power remains
    supporting telemetry and cannot substitute for an operating-state reading.
    """

    def __init__(self, started: float, *, final: bool):
        self.final = final
        self.deadline = started + OBSERVATION_SECONDS
        self.heating_deadline = None
        self.phase = "waiting_for_heat"
        self.last_state_at = None

    def observe(self, state: int, now: float) -> None:
        if self.phase == "heating" and now >= self.heating_deadline:
            raise TimeoutError("Water heater did not recover within 12 hours")
        if state not in RUNNING_STATES | IDLE_STATES:
            self.last_state_at = None
            return
        self.last_state_at = now
        if self.phase == "waiting_for_heat" and now <= self.deadline and state in RUNNING_STATES:
            self.phase = "heating"
            self.heating_deadline = now + RECOVERY_TIMEOUT_SECONDS
        elif self.phase == "heating" and state in IDLE_STATES:
            self.phase = "observing" if self.final else "recovered"
            self.deadline = now + OBSERVATION_SECONDS

    def action(self, now: float) -> str | None:
        if self.phase == "heating" and now >= self.heating_deadline:
            raise TimeoutError("Water heater did not recover within 12 hours")
        if self.last_state_at is None or now - self.last_state_at > STATE_FRESHNESS_SECONDS:
            if now >= self.deadline + RECOVERY_TIMEOUT_SECONDS:
                raise TimeoutError("No fresh operating state available for water-draw recovery")
            return None
        if self.phase == "recovered":
            return "next_draw"
        if self.phase != "heating" and now >= self.deadline:
            return "end_test"
        return None
